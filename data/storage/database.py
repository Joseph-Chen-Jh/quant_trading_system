"""
数据存储层 — 将抓取数据写入 SQLite
"""
import pandas as pd
from loguru import logger
from sqlalchemy import create_engine
from config.settings import DATABASE_PATH


class DataStore:
    """数据持久化管理器"""

    def __init__(self, db_path: str = None):
        self.db_path = db_path or DATABASE_PATH
        self.engine = create_engine(f"sqlite:///{self.db_path}", echo=False)

    # ======================== 股票基础信息 ========================
    def save_stock_basic(self, df: pd.DataFrame, replace: bool = True):
        """保存股票基础信息"""
        if df.empty:
            logger.warning("股票列表为空，跳过")
            return

        cols = {"ts_code", "code", "name", "market", "is_st"}
        available = [c for c in cols if c in df.columns]
        data = df[available].copy()

        if replace:
            data.to_sql("stock_basic", self.engine, if_exists="replace", index=False)
        else:
            # 增量: 先删旧再插入
            with self.engine.begin() as conn:
                for _, row in data.iterrows():
                    conn.execute(
                        "INSERT OR REPLACE INTO stock_basic (ts_code, code, name, market, is_st) "
                        "VALUES (?, ?, ?, ?, ?)",
                        row.get("ts_code"), row.get("code"), row.get("name"),
                        row.get("market"), row.get("is_st")
                    )

        logger.info(f"股票基础信息保存: {len(data)} 条")

    def load_stock_basic(self) -> pd.DataFrame:
        """加载股票基础信息"""
        return pd.read_sql("SELECT * FROM stock_basic", self.engine)

    # ======================== 日线行情 ========================
    def save_daily_price(self, df: pd.DataFrame, replace: bool = False):
        """
        保存日线行情

        Args:
            df:     包含 ts_code, trade_date, open, high, low, close, volume, amount
            replace: True=全量覆盖, False=增量 upsert
        """
        if df.empty:
            return

        required = ["ts_code", "trade_date", "open", "high", "low", "close"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            logger.error(f"缺少必要列: {missing}")
            return

        cols = [c for c in required + ["volume", "amount"] if c in df.columns]
        data = df[cols].copy()

        if replace:
            data.to_sql("daily_price", self.engine, if_exists="replace", index=False)
        else:
            # 按 ts_code + trade_date 去重后插入
            existing = pd.read_sql("SELECT ts_code, trade_date FROM daily_price", self.engine)
            existing_keys = set(zip(existing["ts_code"], existing["trade_date"]))

            new_rows = []
            for _, row in data.iterrows():
                key = (str(row["ts_code"]), str(row["trade_date"]))
                if key not in existing_keys:
                    new_rows.append(row)

            if new_rows:
                pd.DataFrame(new_rows).to_sql(
                    "daily_price", self.engine, if_exists="append", index=False
                )

        logger.info(f"日线数据保存: {len(data)} 行 (增量)")

    def load_daily_price(
        self, ts_code: str = None, start: str = None, end: str = None
    ) -> pd.DataFrame:
        """加载日线行情"""
        sql = "SELECT * FROM daily_price WHERE 1=1"
        params = {}
        if ts_code:
            sql += " AND ts_code = :ts_code"
            params["ts_code"] = ts_code
        if start:
            sql += " AND trade_date >= :start"
            params["start"] = start
        if end:
            sql += " AND trade_date <= :end"
            params["end"] = end
        sql += " ORDER BY ts_code, trade_date"
        return pd.read_sql(sql, self.engine, params=params)

    def get_latest_trade_date(self) -> str:
        """获取数据库中最新交易日"""
        result = pd.read_sql("SELECT MAX(trade_date) AS d FROM daily_price", self.engine)
        val = result["d"].iloc[0]
        return str(val) if val else ""

    # ======================== 指数日线 ========================
    def save_index_daily(self, df: pd.DataFrame, replace: bool = False):
        """保存指数日线"""
        if df.empty:
            return
        if replace:
            df.to_sql("index_daily", self.engine, if_exists="replace", index=False)
        else:
            df.to_sql("index_daily", self.engine, if_exists="append", index=False)
        logger.info(f"指数数据保存: {len(df)} 行")

    # ======================== 财务数据 ========================
    def save_financial_snapshot(self, df: pd.DataFrame):
        """保存财务快照 (PE/PB/市值等)"""
        if df.empty:
            return

        # 快照保存在同一个表，按 ts_code 去重覆盖
        cols = [c for c in ["ts_code", "pe", "pb", "total_mv", "circ_mv", "revenue", "profit"]
                if c in df.columns]
        data = df[cols].copy()

        # 简单方式：删旧插新
        with self.engine.begin() as conn:
            conn.execute("DELETE FROM financial_data")
        data.to_sql("financial_data", self.engine, if_exists="append", index=False)

        logger.info(f"财务快照保存: {len(data)} 条")

    def load_financial_snapshot(self) -> pd.DataFrame:
        """加载财务快照"""
        return pd.read_sql("SELECT * FROM financial_data", self.engine)

    # ======================== 交易记录 ========================
    def save_trade_record(self, record: dict):
        """保存单笔交易记录"""
        df = pd.DataFrame([record])
        df.to_sql("trade_record", self.engine, if_exists="append", index=False)

    # ======================== 净值 ========================
    def save_daily_nav(self, df: pd.DataFrame):
        """保存每日净值"""
        if df.empty:
            return
        # 按日期覆盖
        df.to_sql("daily_nav", self.engine, if_exists="replace", index=False)
        logger.info(f"净值保存: {len(df)} 条")
