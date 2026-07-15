"""
市场环境过滤器

基于沪深300指数的均线位置/斜率, 判断当前是否适合开仓
只在"上涨趋势"时允许 BUY, 震荡/下跌时禁止开仓 (但不影响 SELL)

规则:
    - 规则A (默认): 沪深300收盘价 > MA60 → 允许开仓
    - 规则B: 沪深300 MA60 斜率向上 → 允许开仓
    - 规则A+B: 两者同时满足 → 允许开仓

用法:
    filter = MarketFilter(store, rule="price_above_ma", ma_period=60)
    if filter.can_open_position(date):
        # 执行 BUY
"""
import pandas as pd
from loguru import logger


class MarketFilter:
    """市场环境过滤器 (基于沪深300指数)"""

    INDEX_CODE = "000300.SH"

    def __init__(self, store, rule: str = "price_above_ma", ma_period: int = 60):
        """
        Args:
            store: DataStore 实例
            rule: 过滤规则
                - "price_above_ma": 收盘价 > MA(60)
                - "ma_slope_up": MA(60) 5日斜率向上
                - "both": 两者同时满足
            ma_period: 均线周期 (默认 60)
        """
        self.rule = rule
        self.ma_period = ma_period

        # 预加载指数数据并计算指标
        df = store.load_index_daily(ts_code=self.INDEX_CODE, start="20230101")
        if df.empty:
            raise ValueError(f"无法加载 {self.INDEX_CODE} 数据")
        df = df.sort_values("trade_date").reset_index(drop=True)
        df[f"ma{ma_period}"] = df["close"].rolling(ma_period).mean()
        df["ma_slope_up"] = df[f"ma{ma_period}"] > df[f"ma{ma_period}"].shift(5)
        df["above_ma"] = df["close"] > df[f"ma{ma_period}"]

        # 构建 {trade_date: bool} 查找表
        self._can_open: dict = {}
        for _, row in df.iterrows():
            date = row["trade_date"]
            if pd.isna(row[f"ma{ma_period}"]):
                continue
            if rule == "price_above_ma":
                self._can_open[date] = bool(row["above_ma"])
            elif rule == "ma_slope_up":
                self._can_open[date] = bool(row["ma_slope_up"])
            elif rule == "both":
                self._can_open[date] = bool(row["above_ma"] and row["ma_slope_up"])
            else:
                raise ValueError(f"未知规则: {rule}")

        self.n_total = len(df)
        self.n_can_open = sum(self._can_open.values())
        logger.info(
            f"MarketFilter 初始化: {self.INDEX_CODE} {rule} "
            f"(允许开仓 {self.n_can_open}/{self.n_total} = {self.n_can_open/self.n_total:.1%})"
        )

    def can_open_position(self, trade_date) -> bool:
        """判断指定日期是否允许开仓 (BUY)"""
        if trade_date not in self._can_open:
            # 数据缺失时默认允许 (不阻塞回测)
            return True
        return self._can_open[trade_date]
