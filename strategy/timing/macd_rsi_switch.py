"""
MACD + RSI 策略切换 (Strategy Switching)

基于"趋势市用 MACD, 震荡市用 RSI"的互补思路:
    - MACD 是极端趋势策略, 2025H2 贡献 +36.35% 超额, 但震荡市频繁假信号
    - RSI 多周期是均值回归策略, 震荡市大胜, 但趋势市零交易 (2025H2 -17.43%)
    - 两者优势区间互补, 通过 DIF 零轴判断市场状态进行切换

切换逻辑 (个股级别):
    - 买入信号: DIF > 0 (多头格局) → 用 MACD 金叉 (带零轴过滤)
                DIF <= 0 (空头格局) → 用 RSI 多周期共振 (RSI(14) 上穿 30 + RSI(21) < 50)
    - 卖出信号: 两个策略的卖出信号都生效 (MACD 死叉 + RSI 下穿 70)
      → 确保持仓无论由哪个策略买入, 都能被及时平掉

注意:
    - 切换是"个股级别"的, 每只股票根据自己的 DIF 状态决定用哪个策略的买入信号
    - 卖出信号不切换, 避免持仓因切换规则而无法平仓
    - T 日收盘生成信号 → T+1 开盘成交 (由 PortfolioRunner 保证)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd
import numpy as np
from strategy.base_strategy import BaseStrategy
from strategy.timing.macd import MACDStrategy, _ema
from strategy.timing.rsi_revert import RSIRevertStrategy


class MACDRSISwitchStrategy(BaseStrategy):
    """MACD + RSI 策略切换 (趋势市用 MACD, 震荡市用 RSI)"""

    def __init__(
        self,
        # MACD 参数
        fast_period: int = 12,
        slow_period: int = 26,
        signal_period: int = 9,
        # RSI 参数
        rsi_period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0,
        long_rsi_period: int = 21,
        long_rsi_threshold: float = 50.0,
    ):
        """
        Args:
            fast_period: MACD 快线 EMA 周期 (默认 12)
            slow_period: MACD 慢线 EMA 周期 (默认 26)
            signal_period: MACD 信号线 EMA 周期 (默认 9)
            rsi_period: RSI 计算周期 (默认 14)
            oversold: RSI 超卖阈值 (默认 30)
            overbought: RSI 超买阈值 (默认 70)
            long_rsi_period: 长周期 RSI 周期 (默认 21, 多周期共振)
            long_rsi_threshold: 长周期 RSI 上限 (默认 50)
        """
        super().__init__(name="MACD_RSI_Switch")
        self.fast_period = fast_period
        self.slow_period = slow_period
        self.signal_period = signal_period
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.long_rsi_period = long_rsi_period
        self.long_rsi_threshold = long_rsi_threshold

        # 内部子策略 (复用计算逻辑)
        self._macd = MACDStrategy(
            fast_period=fast_period,
            slow_period=slow_period,
            signal_period=signal_period,
            zero_filter=True,  # 始终启用零轴过滤
        )
        self._rsi = RSIRevertStrategy(
            rsi_period=rsi_period,
            oversold=oversold,
            overbought=overbought,
            multi_period=True,  # 始终启用多周期共振
            long_rsi_period=long_rsi_period,
            long_rsi_threshold=long_rsi_threshold,
        )
        self.params = {
            "fast": fast_period,
            "slow": slow_period,
            "signal": signal_period,
            "rsi_period": rsi_period,
            "oversold": oversold,
            "overbought": overbought,
            "long_rsi_period": long_rsi_period,
            "long_rsi_threshold": long_rsi_threshold,
            "switch_rule": "DIF>0 → MACD buy, DIF<=0 → RSI buy, sell=both",
        }

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        生成策略切换信号

        Args:
            data: 单只股票日线, 必须包含 ts_code, trade_date, close, high, low
        Returns:
            DataFrame with columns:
                ts_code, trade_date, close, dif, rsi, long_rsi, action, source
            action ∈ {BUY, SELL, HOLD}
            source ∈ {MACD, RSI, BOTH} (信号来源, 用于调试)
        """
        required = ["ts_code", "trade_date", "close", "high", "low"]
        for col in required:
            if col not in data.columns:
                raise ValueError(f"输入数据缺少必要列: {col}")

        df = data.sort_values("trade_date").copy().reset_index(drop=True)

        # --- 1. 计算 MACD 指标 ---
        df["ema_fast"] = _ema(df["close"], self.fast_period)
        df["ema_slow"] = _ema(df["close"], self.slow_period)
        df["dif"] = df["ema_fast"] - df["ema_slow"]
        df["dea"] = _ema(df["dif"], self.signal_period)
        df["prev_dif"] = df["dif"].shift(1)
        df["prev_dea"] = df["dea"].shift(1)

        # MACD 金叉 (带零轴过滤) / 死叉
        macd_golden = (df["prev_dif"] <= df["prev_dea"]) & (df["dif"] > df["dea"]) & (df["dif"] > 0)
        macd_death = (df["prev_dif"] >= df["prev_dea"]) & (df["dif"] < df["dea"])

        # --- 2. 计算 RSI 指标 ---
        df["rsi"] = self._rsi._compute_rsi(df["close"])
        df["prev_rsi"] = df["rsi"].shift(1)
        df["long_rsi"] = self._rsi._compute_rsi(df["close"], period=self.long_rsi_period)

        # RSI 多周期共振买入: RSI(14) 上穿 30 且 RSI(21) < 50
        rsi_buy = (
            (df["prev_rsi"] <= self.oversold)
            & (df["rsi"] > self.oversold)
            & (df["long_rsi"] < self.long_rsi_threshold)
        )
        # RSI 卖出: RSI(14) 下穿 70
        rsi_sell = (df["prev_rsi"] >= self.overbought) & (df["rsi"] < self.overbought)

        # --- 3. 策略切换合并 ---
        # 买入: DIF > 0 → MACD 金叉; DIF <= 0 → RSI 多周期
        # 卖出: MACD 死叉 + RSI 下穿 70 (两者并集)
        df["action"] = "HOLD"
        df["source"] = ""

        # 买入信号 (互斥: DIF>0 用 MACD, DIF<=0 用 RSI)
        macd_buy_mask = macd_golden & (df["dif"] > 0)
        rsi_buy_mask = rsi_buy & (df["dif"] <= 0)

        df.loc[macd_buy_mask, "action"] = "BUY"
        df.loc[macd_buy_mask, "source"] = "MACD"
        df.loc[rsi_buy_mask, "action"] = "BUY"
        df.loc[rsi_buy_mask, "source"] = "RSI"

        # 卖出信号 (并集: 两个策略的卖出都生效)
        # 优先级: 若同日既有 MACD 死叉又有 RSI 卖出, 标记为 BOTH
        sell_mask = macd_death | rsi_sell
        df.loc[sell_mask, "action"] = "SELL"
        # 标记卖出来源
        both_sell = macd_death & rsi_sell
        df.loc[macd_death & ~rsi_sell, "source"] = "MACD"
        df.loc[rsi_sell & ~macd_death, "source"] = "RSI"
        df.loc[both_sell, "source"] = "BOTH"

        # 买入信号优先于卖出 (同日既有买入又有卖出时, 取买入)
        # 实际上 MACD 金叉和死叉不会同日发生, RSI 买入和卖出也不会同日发生
        # 但 MACD 买入和 RSI 卖出可能同日发生, 此时取买入
        buy_overrides_sell = macd_buy_mask | rsi_buy_mask
        df.loc[buy_overrides_sell, "action"] = "BUY"

        # DIF/RSI 为 NaN 时强制 HOLD
        df.loc[df["dif"].isna() | df["rsi"].isna() | df["long_rsi"].isna(), "action"] = "HOLD"
        df.loc[df["action"] == "HOLD", "source"] = ""

        return df[["ts_code", "trade_date", "close", "dif", "rsi", "long_rsi", "action", "source"]]


if __name__ == "__main__":
    from data.storage.database import DataStore

    store = DataStore()
    df = store.load_daily_price(ts_code="000001.SZ", start="20210101")
    print(f"数据: {len(df)} 行")

    strategy = MACDRSISwitchStrategy()
    signals = strategy.generate_signals(df)

    trades = signals[signals["action"] != "HOLD"]
    print(f"\n信号数: {len(trades)} (BUY={len(trades[trades.action=='BUY'])}, SELL={len(trades[trades.action=='SELL'])})")
    print("\n买卖点:")
    print(trades[["trade_date", "close", "dif", "rsi", "long_rsi", "action", "source"]].to_string(index=False))
