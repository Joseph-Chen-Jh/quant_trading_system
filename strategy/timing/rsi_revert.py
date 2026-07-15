"""
RSI 均值回归策略 (RSI Reversion)

经典的均值回归策略, 与 MA 趋势跟踪互补:
    - 趋势跟踪 (MA): 适合趋势市, 震荡市频繁假信号
    - 均值回归 (RSI): 适合震荡市, 趋势市过早抄底/踏空

逻辑:
    - RSI 从下方上穿 oversold (默认 30) → BUY  (超卖反弹)
    - RSI 从上方下穿 overbought (默认 70) → SELL (超买回落)

参数:
    - rsi_period: RSI 计算周期 (默认 14, Wilder 标准)
    - oversold: 超卖阈值 (默认 30)
    - overbought: 超买阈值 (默认 70)

注意:
    RSI 用 Wilder 平滑法 (与 ADX 一致), 非 SMA。
    T 日收盘生成信号 → T+1 开盘成交 (由 PortfolioRunner 保证)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd
import numpy as np
from strategy.base_strategy import BaseStrategy


class RSIRevertStrategy(BaseStrategy):
    """RSI 超卖反弹策略 (均值回归)"""

    def __init__(
        self,
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
    ):
        """
        Args:
            rsi_period: RSI 计算周期 (默认 14)
            oversold: 超卖阈值, RSI 上穿此值时买入 (默认 30)
            overbought: 超买阈值, RSI 下穿此值时卖出 (默认 70)
        """
        super().__init__(name="RSI_Revert")
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.params = {
            "rsi_period": rsi_period,
            "oversold": oversold,
            "overbought": overbought,
        }

    def _compute_rsi(self, close: pd.Series) -> pd.Series:
        """
        计算 RSI (Wilder 平滑法)

        RSI = 100 - 100 / (1 + RS)
        RS = avg_gain / avg_loss
        avg_gain/avg_loss 用 Wilder 平滑 (等价于 EMA alpha=1/period)
        """
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        # Wilder 平滑: 第一个值用 SMA, 后续用递推
        avg_gain = pd.Series(np.nan, index=close.index)
        avg_loss = pd.Series(np.nan, index=close.index)

        # 第一个有效窗口 (前 period 天的 SMA)
        period = self.rsi_period
        if len(close) <= period:
            return pd.Series(50.0, index=close.index)

        avg_gain.iloc[period] = gain.iloc[1:period + 1].mean()
        avg_loss.iloc[period] = loss.iloc[1:period + 1].mean()

        for i in range(period + 1, len(close)):
            avg_gain.iloc[i] = (avg_gain.iloc[i - 1] * (period - 1) + gain.iloc[i]) / period
            avg_loss.iloc[i] = (avg_loss.iloc[i - 1] * (period - 1) + loss.iloc[i]) / period

        # RSI
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi = 100 - 100 / (1 + rs)
        # avg_loss=0 时 (连续上涨), RSI=100
        rsi = rsi.fillna(100.0)
        return rsi

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        生成 RSI 超买超卖信号

        Args:
            data: 单只股票日线, 必须包含 ts_code, trade_date, close
        Returns:
            DataFrame with columns:
                ts_code, trade_date, close, rsi, action
            action ∈ {BUY, SELL, HOLD}
        """
        required = ["ts_code", "trade_date", "close"]
        for col in required:
            if col not in data.columns:
                raise ValueError(f"输入数据缺少必要列: {col}")

        df = data.sort_values("trade_date").copy().reset_index(drop=True)
        df["rsi"] = self._compute_rsi(df["close"])
        df["prev_rsi"] = df["rsi"].shift(1)

        df["action"] = "HOLD"

        # BUY: RSI 从下方上穿 oversold (从超卖区回升)
        buy_signal = (df["prev_rsi"] <= self.oversold) & (df["rsi"] > self.oversold)
        df.loc[buy_signal, "action"] = "BUY"

        # SELL: RSI 从上方下穿 overbought (从超买区回落)
        sell_signal = (df["prev_rsi"] >= self.overbought) & (df["rsi"] < self.overbought)
        df.loc[sell_signal, "action"] = "SELL"

        # 前 rsi_period 天 RSI 为 NaN, 强制 HOLD
        df.loc[df["rsi"].isna(), "action"] = "HOLD"

        return df[["ts_code", "trade_date", "close", "rsi", "action"]]


if __name__ == "__main__":
    from data.storage.database import DataStore

    store = DataStore()
    df = store.load_daily_price(ts_code="000001.SZ", start="20240101")
    print(f"数据: {len(df)} 行")

    strategy = RSIRevertStrategy(rsi_period=14, oversold=30, overbought=70)
    signals = strategy.generate_signals(df)

    trades = signals[signals["action"] != "HOLD"]
    print(f"\n信号数: {len(trades)} (BUY={len(trades[trades.action=='BUY'])}, SELL={len(trades[trades.action=='SELL'])})")
    print("\n买卖点:")
    print(trades[["trade_date", "close", "rsi", "action"]].to_string(index=False))
