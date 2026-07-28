"""
MACD 指标策略 (Moving Average Convergence Divergence)

经典的双指数平滑趋势跟踪策略, 由 Gerald Appel 于 1970 年代提出:
    - DIF = EMA(短) - EMA(长)            反映短期与长期趋势的偏离 (速度)
    - DEA = EMA(DIF, signal)             DIF 的信号线 (平滑后的速度)
    - 柱状图 = 2 * (DIF - DEA)           反映动量变化 (加速度)

逻辑:
    - 金叉: DIF 从下方上穿 DEA → BUY
    - 死叉: DIF 从上方下穿 DEA → SELL
    - 其他情况 → HOLD

参数:
    - fast_period: 快线 EMA 周期 (默认 12, MACD 标准)
    - slow_period: 慢线 EMA 周期 (默认 26, MACD 标准)
    - signal_period: 信号线 EMA 周期 (默认 9, MACD 标准)

可选:
    - zero_filter: 是否启用零轴过滤 (默认 False)
        启用时: 只在 DIF > 0 (多头格局) 时允许金叉买入
        避免在空头市场中的假金叉信号

注意:
    - EMA 首个值用前 N 个值的 SMA 作为种子 (与 Wilder 平滑一致)
    - T 日收盘生成信号 → T+1 开盘成交 (由 PortfolioRunner 保证)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd
import numpy as np
from strategy.base_strategy import BaseStrategy


def _ema(series: pd.Series, period: int) -> pd.Series:
    """
    计算 EMA (指数移动平均)

    EMA[i] = alpha * series[i] + (1 - alpha) * EMA[i-1]
    其中 alpha = 2 / (period + 1)

    首个有效值用前 period 个值的 SMA 作为种子 (与常见行情软件一致)

    Args:
        series: 输入序列 (通常是收盘价)
        period: EMA 周期
    """
    alpha = 2.0 / (period + 1)
    ema = pd.Series(np.nan, index=series.index)

    if len(series) < period:
        return ema

    # 种子: 前 period 个有效值的 SMA
    first_valid = series.dropna()
    if len(first_valid) < period:
        return ema
    seed_idx = first_valid.index[period - 1]
    ema.loc[seed_idx] = first_valid.iloc[:period].mean()

    # 后续递推
    seed_pos = series.index.get_loc(seed_idx)
    for i in range(seed_pos + 1, len(series)):
        prev = ema.iloc[i - 1]
        cur = series.iloc[i]
        if pd.notna(prev) and pd.notna(cur):
            ema.iloc[i] = alpha * cur + (1 - alpha) * prev

    return ema


class MACDStrategy(BaseStrategy):
    """MACD 金叉死叉策略"""

    def __init__(
        self,
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        zero_filter: bool = False,
    ):
        """
        Args:
            fast_period: 快线 EMA 周期 (默认 12)
            slow_period: 慢线 EMA 周期 (默认 26)
            signal_period: 信号线 EMA 周期 (默认 9)
            zero_filter: 是否启用零轴过滤 (默认 False)
                True 时只在 DIF > 0 (多头格局) 允许金叉买入
        """
        super().__init__(name="MACD")
        if fast_period >= slow_period:
            raise ValueError("fast_period 必须小于 slow_period")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.zero_filter = zero_filter
        self.params = {
            "fast": fast_period,
            "slow": slow_period,
            "signal": signal_period,
            "zero_filter": zero_filter,
        }

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        生成 MACD 金叉死叉信号

        Args:
            data: 单只股票日线, 必须包含 ts_code, trade_date, close
        Returns:
            DataFrame with columns:
                ts_code, trade_date, close, dif, dea, hist, action
            action ∈ {BUY, SELL, HOLD}
        """
        required = ["ts_code", "trade_date", "close"]
        for col in required:
            if col not in data.columns:
                raise ValueError(f"输入数据缺少必要列: {col}")

        df = data.sort_values("trade_date").copy().reset_index(drop=True)

        # 计算 EMA 快慢线
        df["ema_fast"] = _ema(df["close"], self.fast_period)
        df["ema_slow"] = _ema(df["close"], self.slow_period)

        # DIF: 快慢线差离值
        df["dif"] = df["ema_fast"] - df["ema_slow"]

        # DEA: DIF 的信号线 (对 DIF 做 EMA 平滑)
        # 注意: DIF 前 slow_period-1 天为 NaN, _ema 内部会跳过 NaN
        df["dea"] = _ema(df["dif"], self.signal_period)

        # 柱状图: 2 * (DIF - DEA)
        df["hist"] = 2 * (df["dif"] - df["dea"])

        df["prev_dif"] = df["dif"].shift(1)
        df["prev_dea"] = df["dea"].shift(1)

        df["action"] = "HOLD"

        # 金叉: 前一日 DIF <= DEA, 今日 DIF > DEA
        golden_cross = (df["prev_dif"] <= df["prev_dea"]) & (df["dif"] > df["dea"])
        # 死叉: 前一日 DIF >= DEA, 今日 DIF < DEA
        death_cross = (df["prev_dif"] >= df["prev_dea"]) & (df["dif"] < df["dea"])

        # 零轴过滤: 只在 DIF > 0 时允许金叉买入
        if self.zero_filter:
            golden_cross = golden_cross & (df["dif"] > 0)

        df.loc[golden_cross, "action"] = "BUY"
        df.loc[death_cross, "action"] = "SELL"

        # DIF 或 DEA 为 NaN 时 (前 slow_period + signal_period 天), 强制 HOLD
        df.loc[df["dif"].isna() | df["dea"].isna(), "action"] = "HOLD"

        return df[["ts_code", "trade_date", "close", "dif", "dea", "hist", "action"]]


if __name__ == "__main__":
    from data.storage.database import DataStore

    store = DataStore()
    df = store.load_daily_price(ts_code="000001.SZ", start="20240101")
    print(f"数据: {len(df)} 行")

    strategy = MACDStrategy(fast_period=12, slow_period=26, signal_period=9)
    signals = strategy.generate_signals(df)

    trades = signals[signals["action"] != "HOLD"]
    print(f"\n信号数: {len(trades)} (BUY={len(trades[trades.action=='BUY'])}, SELL={len(trades[trades.action=='SELL'])})")
    print("\n买卖点:")
    print(trades[["trade_date", "close", "dif", "dea", "hist", "action"]].to_string(index=False))
