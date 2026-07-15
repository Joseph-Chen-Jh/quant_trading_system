"""
动态仓位管理器

基于沪深300指数的均线位置, 动态调整开仓资金比例
不是二元开关 (开/关), 而是连续调光 (满仓/半仓/轻仓)

核心思路:
    - 价格远高于 MA60 (强趋势): 满仓 (budget_ratio = 0.9)
    - 价格在 MA60 附近 (震荡): 半仓 (budget_ratio = 0.45)
    - 价格远低于 MA60 (下跌): 轻仓 (budget_ratio = 0.1)

用线性插值平滑过渡, 避免均线指标的滞后性导致的"追涨杀跌"

用法:
    scaler = PositionScaler(store, ma_period=60, full_ratio=0.9, light_ratio=0.1)
    budget_ratio = scaler.get_budget_ratio(date)
    # 在资金分配时用 budget_ratio 替代固定的 0.9
"""
import pandas as pd
import numpy as np
from loguru import logger


class PositionScaler:
    """动态仓位管理器 (基于沪深300均线位置)"""

    INDEX_CODE = "000300.SH"

    def __init__(
        self,
        store,
        ma_period: int = 60,
        full_ratio: float = 0.9,
        light_ratio: float = 0.1,
        strong_threshold: float = 0.05,  # 价格高于MA60 5% 算强趋势
        weak_threshold: float = -0.05,   # 价格低于MA60 5% 算弱趋势
    ):
        """
        Args:
            store: DataStore 实例
            ma_period: 均线周期 (默认 60)
            full_ratio: 强趋势时的资金使用比例 (默认 0.9)
            light_ratio: 弱趋势时的资金使用比例 (默认 0.1)
            strong_threshold: 价格高于MA60多少算强趋势 (默认 5%)
            weak_threshold: 价格低于MA60多少算弱趋势 (默认 -5%)
        """
        self.full_ratio = full_ratio
        self.light_ratio = light_ratio
        self.strong_threshold = strong_threshold
        self.weak_threshold = weak_threshold

        # 预加载指数数据
        df = store.load_index_daily(ts_code=self.INDEX_CODE, start="20230101")
        if df.empty:
            raise ValueError(f"无法加载 {self.INDEX_CODE} 数据")
        df = df.sort_values("trade_date").reset_index(drop=True)
        df[f"ma{ma_period}"] = df["close"].rolling(ma_period).mean()

        # 计算 (price - ma) / ma, 衡量价格偏离均线的程度
        df["price_deviation"] = (df["close"] - df[f"ma{ma_period}"]) / df[f"ma{ma_period}"]

        # 线性插值计算 budget_ratio:
        #   deviation >= strong_threshold → full_ratio (0.9)
        #   deviation <= weak_threshold   → light_ratio (0.1)
        #   中间线性插值
        df["budget_ratio"] = np.interp(
            df["price_deviation"],
            [weak_threshold, 0, strong_threshold],
            [light_ratio, (full_ratio + light_ratio) / 2, full_ratio],
        )
        # 超出范围截断
        df["budget_ratio"] = df["budget_ratio"].clip(light_ratio, full_ratio)

        # 构建 {trade_date: budget_ratio} 查找表
        self._ratios: dict = {}
        for _, row in df.iterrows():
            if pd.isna(row[f"ma{ma_period}"]):
                continue
            self._ratios[row["trade_date"]] = float(row["budget_ratio"])

        self.n_total = len(df)
        valid = df.dropna(subset=[f"ma{ma_period}"])
        self.avg_ratio = valid["budget_ratio"].mean() if len(valid) > 0 else 0.5
        logger.info(
            f"PositionScaler 初始化: {self.INDEX_CODE} MA{ma_period} "
            f"(平均仓位 {self.avg_ratio:.1%}, "
            f"满仓阈值 +{strong_threshold:.0%}, 轻仓阈值 {weak_threshold:.0%})"
        )

    def get_budget_ratio(self, trade_date) -> float:
        """获取指定日期的资金使用比例 (0.1 ~ 0.9)"""
        if trade_date not in self._ratios:
            # 数据缺失时用中等仓位
            return (self.full_ratio + self.light_ratio) / 2
        return self._ratios[trade_date]
