"""
选股策略回测编排器

与 PortfolioRunner (择时策略) 的差异:
    - 择时策略每天可能产生信号, T+1 开盘成交
    - 选股策略在调仓日 (月度/季度) 一次性换仓, 等权持有

调仓逻辑:
    1. 调仓日 T 收盘后, 策略选出目标股票池 (list of ts_code)
    2. T+1 开盘: 卖出不在目标池的持仓, 买入新进目标池的股票
    3. 等权分配: 目标仓位 = 总资产 / top_n
    4. 已有持仓且仍在目标池的股票: 不调整 (减少交易成本)
    5. 非调仓日: 不操作, 每日按收盘价更新市值
"""
from typing import Dict, List, Optional
import pandas as pd
from loguru import logger

from data.storage.database import DataStore
from simulation.account import VirtualAccount
from simulation.order_manager import OrderManager
from simulation.scheduler import SimulationScheduler


class SelectionRunner:
    """选股策略回测编排器"""

    def __init__(
        self,
        strategy,
        account: VirtualAccount,
        scheduler: SimulationScheduler,
        candidate_pool: List[str],
    ):
        """
        Args:
            strategy:        选股策略实例 (需有 recommend(pe_data, current_date) 方法)
            account:         虚拟账户
            scheduler:       交易调度器
            candidate_pool:  候选股票池 ts_code 列表 (从中选股)
        """
        self.strategy = strategy
        self.account = account
        self.scheduler = scheduler
        self.candidate_pool = candidate_pool

        # 日线数据: {ts_code: DataFrame}
        self.stock_data: Dict[str, pd.DataFrame] = {}
        # PE 数据: {ts_code: DataFrame}
        self.pe_data: Dict[str, pd.DataFrame] = {}

        # 调仓历史 (用于分析)
        self.rebalance_log: List[dict] = []

    def load_data(
        self,
        store: DataStore,
        start_date: str,
        end_date: str = None,
    ):
        """
        加载候选池所有股票的日线 + PE 数据

        Args:
            store:        DataStore
            start_date:   回测起始日期
            end_date:     回测截止日期 (None=到最新)
        """
        # 1. 加载日线数据
        total = len(self.candidate_pool)
        for i, ts_code in enumerate(self.candidate_pool, 1):
            df = store.load_daily_price(ts_code=ts_code, start=start_date, end=end_date)
            if df.empty:
                logger.warning(f"[{i}/{total}] {ts_code} 日线数据为空, 跳过")
                continue
            self.stock_data[ts_code] = df
            logger.debug(
                f"[{i}/{total}] {ts_code} 日线: {len(df)} 行 "
                f"({df['trade_date'].min()} ~ {df['trade_date'].max()})"
            )

        logger.info(f"日线数据加载完成: {len(self.stock_data)}/{total} 只")

        # 2. 加载 PE 数据 (从 quant.db: pe_history 表)
        pe_loaded = 0
        for ts_code in self.candidate_pool:
            df = store.load_pe_history(ts_code=ts_code)
            if not df.empty and "pe" in df.columns:
                self.pe_data[ts_code] = df
                pe_loaded += 1
            else:
                logger.warning(f"{ts_code} 无 PE 数据")

        logger.info(f"PE 数据加载完成: {pe_loaded}/{total} 只")

    def run_backtest(self):
        """
        执行选股回测

        流程:
            1. 计算所有调仓日
            2. 逐日遍历:
               - 非调仓日: 只更新持仓市值
               - 调仓日: T 日收盘后选股 → T+1 开盘换仓
        """
        if not self.stock_data:
            logger.error("无可用数据, 终止回测")
            return

        # 1. 计算所有交易日 (候选池的并集)
        all_dates = sorted(set().union(
            *[set(df["trade_date"]) for df in self.stock_data.values()]
        ))
        logger.info(f"回测区间: {all_dates[0]} ~ {all_dates[-1]}, 共 {len(all_dates)} 个交易日")

        # 2. 计算调仓日
        rebalance_dates = set(self.strategy.get_rebalance_dates(all_dates))
        logger.info(f"调仓日: {len(rebalance_dates)} 个 ({self.strategy.rebalance_freq})")

        # 3. 价格查找表
        price_lookup = {}
        for ts_code, df in self.stock_data.items():
            price_lookup[ts_code] = {
                row["trade_date"]: (float(row["open"]), float(row["close"]))
                for _, row in df.iterrows()
            }

        # 4. 逐日回测
        pending_rebalance = None  # 待执行的调仓信号 (T+1 执行)

        for i, date in enumerate(all_dates, 1):
            if i % 100 == 0:
                logger.info(f"进度: {i}/{len(all_dates)}")

            # 1. 收集当日收盘价
            close_prices = {}
            for ts_code, lookup in price_lookup.items():
                if date in lookup:
                    close_prices[ts_code] = lookup[date][1]

            # 2. 执行昨日信号 (T+1 开盘成交)
            signals_to_execute = pending_rebalance or []
            pending_rebalance = None

            if signals_to_execute:
                enriched = self._price_signals(signals_to_execute, price_lookup, date)
                self.scheduler.run_daily(date, enriched, close_prices)
            else:
                # 无信号也要更新市值和日终结算
                self.scheduler.run_daily(date, [], close_prices)

            # 3. 调仓日收盘后选股
            if date in rebalance_dates:
                target = self.strategy.recommend(self.pe_data, date)
                target_codes = [s["ts_code"] for s in target]

                # 生成换仓信号 (T+1 执行)
                pending_rebalance = self._build_rebalance_signals(
                    target_codes, price_lookup, date
                )

                self.rebalance_log.append({
                    "date": date,
                    "target": target_codes,
                    "signals": len(pending_rebalance),
                })

                if pending_rebalance:
                    logger.info(
                        f"调仓 {date}: 目标 {len(target_codes)} 只, "
                        f"换仓信号 {len(pending_rebalance)} 个 "
                        f"(卖 {sum(1 for s in pending_rebalance if s['action']=='SELL')}, "
                        f"买 {sum(1 for s in pending_rebalance if s['action']=='BUY')})"
                    )

        logger.info(f"回测完成: 累计收益率 {self.account.total_return:.2%}")

    def _build_rebalance_signals(
        self,
        target_codes: List[str],
        price_lookup: Dict,
        date: str,
    ) -> List[dict]:
        """
        根据目标股票池生成换仓信号

        策略:
            - 不在目标池的持仓 → SELL (清仓)
            - 在目标池但未持有的 → BUY (等权)
            - 在目标池且已持有的 → HOLD (不调整, 减少交易成本)
        """
        signals = []

        # 卖出: 持有但不在目标池的股票
        for ts_code in list(self.account.positions.keys()):
            if ts_code not in target_codes:
                signals.append({
                    "ts_code": ts_code,
                    "action": "SELL",
                    "price": 0,  # T+1 开盘价在执行时填入
                    "reason": "调仓换出",
                })

        # 买入: 在目标池但未持有的股票
        current_holdings = set(self.account.positions.keys())
        new_buys = [c for c in target_codes if c not in current_holdings]

        if new_buys:
            # 等权分配: 每只新买入股票的目标仓位 = 总资产 / top_n
            target_value_per_stock = self.account.total_asset / self.strategy.top_n

            for ts_code in new_buys:
                # 用当日收盘价估算股数 (实际成交价是 T+1 开盘)
                if ts_code in price_lookup and date in price_lookup[ts_code]:
                    ref_price = price_lookup[ts_code][date][1]  # close
                    volume = int(target_value_per_stock / ref_price / 100) * 100
                    if volume > 0:
                        signals.append({
                            "ts_code": ts_code,
                            "action": "BUY",
                            "price": ref_price,  # T+1 开盘价在执行时替换
                            "volume": volume,
                            "reason": "调仓换入",
                        })

        return signals

    def _price_signals(
        self,
        signals: List[dict],
        price_lookup: Dict,
        exec_date: str,
    ) -> List[dict]:
        """用 T+1 开盘价替换信号价格"""
        enriched = []
        for sig in signals:
            ts_code = sig["ts_code"]
            if ts_code in price_lookup and exec_date in price_lookup[ts_code]:
                open_price = price_lookup[ts_code][exec_date][0]
                sig["price"] = open_price
                # BUY 信号: 按新价格重算 volume
                if sig["action"] == "BUY" and "volume" in sig:
                    target_value = self.account.total_asset / self.strategy.top_n
                    volume = int(target_value / open_price / 100) * 100
                    if volume > 0:
                        sig["volume"] = volume
                    else:
                        continue  # 买不起, 跳过
                enriched.append(sig)
            else:
                logger.debug(f"{ts_code} 在 {exec_date} 无价格, 跳过")
        return enriched
