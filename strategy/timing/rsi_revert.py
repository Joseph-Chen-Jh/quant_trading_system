"""
RSI 均值回归策略 (RSI Reversion)

经典的均值回归策略, 与 MA 趋势跟踪互补:
    - 趋势跟踪 (MA): 适合趋势市, 震荡市频繁假信号
    - 均值回归 (RSI): 适合震荡市, 趋势市过早抄底/踏空

逻辑:
    - 固定阈值模式: RSI 从下方上穿 oversold (默认 30) → BUY, 从上方下穿 overbought (默认 70) → SELL
    - 自适应模式: 用过去 lookback 天 RSI 的 low_q/high_q 分位数作为阈值 (4.15 节验证失败)
    - 波动率分组模式: 按个股年化波动率分组, 每组用不同固定阈值 (4.16 节验证失败)
    - 多周期共振模式: RSI(14) 上穿 30 买入 + RSI(21) < long_threshold 确认
        - 只在"短期超卖 + 长期仍弱"时买入, 避免在长期超买时接飞刀
        - 卖出信号不变 (RSI(14) 下穿 70), 卖出要果断不需要多周期确认
    - 趋势适配模式 (trend_adaptive, 需配合 multi_period):
        - 上涨趋势 (价格>MA60 且 MA60 上升) 时放宽 RSI 阈值, 让策略在趋势上涨市也能参与
        - 解决多周期 RSI 在 2025H2/2026H1 上涨趋势市零交易的问题
        - 非上涨趋势时使用原始多周期 RSI 阈值, 保持震荡市的信号质量

参数:
    - rsi_period: RSI 计算周期 (默认 14, Wilder 标准)
    - oversold: 超卖阈值 (默认 30, 固定模式)
    - overbought: 超买阈值 (默认 70, 固定模式)
    - adaptive: 是否启用自适应分位数阈值 (默认 False, 4.15 节验证失败)
    - lookback: 自适应模式的滚动窗口天数 (默认 60)
    - low_q: 超卖分位数 (默认 0.10)
    - high_q: 超买分位数 (默认 0.90)
    - vol_grouped: 是否启用波动率分组模式 (默认 False, 4.16 节验证失败)
    - vol_lookback: 波动率分组模式的波动率回看天数 (默认 60)
    - vol_high: 高波动阈值 (默认 0.40)
    - vol_low: 低波动阈值 (默认 0.30)
    - multi_period: 是否启用多周期共振模式 (默认 False)
    - long_rsi_period: 长周期 RSI 计算周期 (默认 21)
    - long_rsi_threshold: 长周期 RSI 上限, 超过则不买 (默认 50)
    - trend_adaptive: 是否启用趋势适配模式 (默认 False, 需配合 multi_period)
    - trend_ma_period: 趋势判断的 MA 周期 (默认 60)
    - trend_slope_window: MA 斜率比较窗口天数 (默认 5)
    - relaxed_oversold: 上涨趋势时的放宽超卖阈值 (默认 40)
    - relaxed_long_threshold: 上涨趋势时的放宽长周期 RSI 上限 (默认 60)

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
        adaptive: bool = False,
        lookback: int = 60,
        low_q: float = 0.10,
        high_q: float = 0.90,
        vol_grouped: bool = False,
        vol_lookback: int = 60,
        vol_high: float = 0.40,
        vol_low: float = 0.30,
        multi_period: bool = False,
        long_rsi_period: int = 21,
        long_rsi_threshold: float = 50.0,
        trend_adaptive: bool = False,
        trend_ma_period: int = 60,
        trend_slope_window: int = 5,
        relaxed_oversold: float = 40.0,
        relaxed_long_threshold: float = 60.0,
    ):
        """
        Args:
            rsi_period: RSI 计算周期 (默认 14)
            oversold: 超卖阈值, RSI 上穿此值时买入 (默认 30, 固定模式)
            overbought: 超买阈值, RSI 下穿此值时卖出 (默认 70, 固定模式)
            adaptive: 是否启用自适应分位数阈值 (默认 False)
            lookback: 自适应模式的滚动窗口天数 (默认 60)
            low_q: 超卖分位数 (默认 0.10)
            high_q: 超买分位数 (默认 0.90)
            vol_grouped: 是否启用波动率分组模式 (默认 False)
            vol_lookback: 波动率分组模式的波动率回看天数 (默认 60)
            vol_high: 高波动阈值 (默认 0.40, 年化)
            vol_low: 低波动阈值 (默认 0.30, 年化)
            multi_period: 是否启用多周期共振模式 (默认 False)
            long_rsi_period: 长周期 RSI 计算周期 (默认 21)
            long_rsi_threshold: 长周期 RSI 上限, 超过则不买 (默认 50)
            trend_adaptive: 是否启用趋势适配模式 (默认 False, 需配合 multi_period)
            trend_ma_period: 趋势判断的 MA 周期 (默认 60)
            trend_slope_window: MA 斜率比较窗口天数 (默认 5)
            relaxed_oversold: 上涨趋势时的放宽超卖阈值 (默认 40)
            relaxed_long_threshold: 上涨趋势时的放宽长周期 RSI 上限 (默认 60)
        """
        super().__init__(name="RSI_Revert")
        self.rsi_period = rsi_period
        self.oversold = oversold
        self.overbought = overbought
        self.adaptive = adaptive
        self.lookback = lookback
        self.low_q = low_q
        self.high_q = high_q
        self.vol_grouped = vol_grouped
        self.vol_lookback = vol_lookback
        self.vol_high = vol_high
        self.vol_low = vol_low
        self.multi_period = multi_period
        self.long_rsi_period = long_rsi_period
        self.long_rsi_threshold = long_rsi_threshold
        self.trend_adaptive = trend_adaptive
        self.trend_ma_period = trend_ma_period
        self.trend_slope_window = trend_slope_window
        self.relaxed_oversold = relaxed_oversold
        self.relaxed_long_threshold = relaxed_long_threshold
        self.params = {
            "rsi_period": rsi_period,
            "oversold": oversold,
            "overbought": overbought,
            "adaptive": adaptive,
            "lookback": lookback,
            "low_q": low_q,
            "high_q": high_q,
            "vol_grouped": vol_grouped,
            "vol_lookback": vol_lookback,
            "vol_high": vol_high,
            "vol_low": vol_low,
            "multi_period": multi_period,
            "long_rsi_period": long_rsi_period,
            "long_rsi_threshold": long_rsi_threshold,
            "trend_adaptive": trend_adaptive,
            "trend_ma_period": trend_ma_period,
            "trend_slope_window": trend_slope_window,
            "relaxed_oversold": relaxed_oversold,
            "relaxed_long_threshold": relaxed_long_threshold,
        }

    def _compute_rsi(self, close: pd.Series, period: int = None) -> pd.Series:
        """
        计算 RSI (Wilder 平滑法)

        RSI = 100 - 100 / (1 + RS)
        RS = avg_gain / avg_loss
        avg_gain/avg_loss 用 Wilder 平滑 (等价于 EMA alpha=1/period)

        Args:
            close: 收盘价序列
            period: RSI 周期 (默认用 self.rsi_period, 多周期模式可指定)
        """
        if period is None:
            period = self.rsi_period

        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        # Wilder 平滑: 第一个值用 SMA, 后续用递推
        avg_gain = pd.Series(np.nan, index=close.index)
        avg_loss = pd.Series(np.nan, index=close.index)

        # 第一个有效窗口 (前 period 天的 SMA)
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

    def _compute_rolling_vol(self, close: pd.Series) -> pd.Series:
        """计算滚动年化波动率 (用于波动率分组模式)"""
        daily_ret = close.pct_change()
        # 用 shift(1) 确保只用到 T-1 及之前的数据 (避免未来函数)
        rolling_vol = daily_ret.shift(1).rolling(self.vol_lookback).std() * np.sqrt(244)
        return rolling_vol

    def _get_grouped_thresholds(self, vol: float) -> tuple:
        """
        根据年化波动率返回 (oversold, overbought) 阈值
        - 高波动 (>vol_high): 20/80 (更极端, 减少假信号)
        - 中波动 (vol_low~vol_high): 30/70 (标准)
        - 低波动 (<vol_low): None (跳过, RSI 在低波动股上无意义)
        """
        if vol is None or np.isnan(vol):
            return (None, None)
        if vol >= self.vol_high:
            return (20.0, 80.0)
        elif vol >= self.vol_low:
            return (30.0, 70.0)
        else:
            return (None, None)

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

        if self.multi_period:
            # 多周期共振模式 (思路B): RSI(14) 上穿 30 买入 + RSI(21) < long_threshold 确认
            # 卖出信号不变 (RSI(14) 下穿 70)
            df["long_rsi"] = self._compute_rsi(df["close"], period=self.long_rsi_period)

            if self.trend_adaptive:
                # 趋势适配模式: 上涨趋势 (价格>MA60 且 MA60 上升) 时放宽 RSI 阈值
                df["trend_ma"] = df["close"].rolling(self.trend_ma_period).mean()
                df["trend_ma_prev"] = df["trend_ma"].shift(self.trend_slope_window)
                uptrend = (df["close"] > df["trend_ma"]) & (df["trend_ma"] > df["trend_ma_prev"])
                # 动态阈值: 上涨趋势用放宽阈值, 否则用原始阈值
                df["eff_oversold"] = np.where(uptrend, self.relaxed_oversold, self.oversold)
                df["eff_long_thr"] = np.where(uptrend, self.relaxed_long_threshold, self.long_rsi_threshold)

                # BUY: RSI(14) 上穿 eff_oversold 且 RSI(21) < eff_long_thr
                buy_signal = (
                    (df["prev_rsi"] <= df["eff_oversold"]) & (df["rsi"] > df["eff_oversold"])
                    & (df["long_rsi"] < df["eff_long_thr"])
                )
                df.loc[buy_signal, "action"] = "BUY"
                # 长周期 RSI 或趋势 MA 为 NaN 时强制 HOLD
                df.loc[df["long_rsi"].isna() | df["trend_ma"].isna() | df["trend_ma_prev"].isna(), "action"] = "HOLD"
            else:
                # BUY: RSI(14) 从下方上穿 oversold 且 RSI(21) < long_threshold
                # (短期超卖反弹 + 长期仍偏弱, 有反弹空间)
                buy_signal = (
                    (df["prev_rsi"] <= self.oversold) & (df["rsi"] > self.oversold)
                    & (df["long_rsi"] < self.long_rsi_threshold)
                )
                df.loc[buy_signal, "action"] = "BUY"

                # 长周期 RSI 为 NaN 时强制 HOLD
                df.loc[df["long_rsi"].isna(), "action"] = "HOLD"

            # SELL: RSI(14) 从上方下穿 overbought (不变)
            sell_signal = (df["prev_rsi"] >= self.overbought) & (df["rsi"] < self.overbought)
            df.loc[sell_signal, "action"] = "SELL"
        elif self.vol_grouped:
            # 波动率分组模式: 按个股滚动波动率选阈值
            df["vol"] = self._compute_rolling_vol(df["close"])
            # 逐行判断 (每行的波动率可能不同, 阈值随之变化)
            for idx in df.index:
                if pd.isna(df.loc[idx, "rsi"]) or pd.isna(df.loc[idx, "prev_rsi"]):
                    continue
                if pd.isna(df.loc[idx, "vol"]):
                    continue
                vol = df.loc[idx, "vol"]
                os_thr, ob_thr = self._get_grouped_thresholds(vol)
                if os_thr is None:
                    continue  # 低波动股跳过
                prev_rsi = df.loc[idx, "prev_rsi"]
                cur_rsi = df.loc[idx, "rsi"]
                # BUY: prev_rsi <= os_thr 且 rsi > os_thr
                if prev_rsi <= os_thr and cur_rsi > os_thr:
                    df.loc[idx, "action"] = "BUY"
                # SELL: prev_rsi >= ob_thr 且 rsi < ob_thr
                elif prev_rsi >= ob_thr and cur_rsi < ob_thr:
                    df.loc[idx, "action"] = "SELL"
        elif self.adaptive:
            # 自适应模式: 滚动分位数阈值
            # 用当前日之前 lookback 天的 RSI 计算分位数 (不含当日, 避免未来函数)
            rsi_series = df["rsi"]
            low_thr = rsi_series.shift(1).rolling(self.lookback).quantile(self.low_q)
            high_thr = rsi_series.shift(1).rolling(self.lookback).quantile(self.high_q)
            df["low_thr"] = low_thr
            df["high_thr"] = high_thr

            # BUY: prev_rsi <= low_thr 且 rsi > low_thr (从相对超卖回升)
            buy_signal = (df["prev_rsi"] <= low_thr) & (df["rsi"] > low_thr)
            df.loc[buy_signal, "action"] = "BUY"

            # SELL: prev_rsi >= high_thr 且 rsi < high_thr (从相对超买回落)
            sell_signal = (df["prev_rsi"] >= high_thr) & (df["rsi"] < high_thr)
            df.loc[sell_signal, "action"] = "SELL"
        else:
            # 固定阈值模式
            buy_signal = (df["prev_rsi"] <= self.oversold) & (df["rsi"] > self.oversold)
            df.loc[buy_signal, "action"] = "BUY"

            sell_signal = (df["prev_rsi"] >= self.overbought) & (df["rsi"] < self.overbought)
            df.loc[sell_signal, "action"] = "SELL"

        # 前 rsi_period 天 RSI 为 NaN, 强制 HOLD
        df.loc[df["rsi"].isna(), "action"] = "HOLD"
        # 自适应模式下, 滚动窗口不足时也强制 HOLD
        if self.adaptive:
            df.loc[df["low_thr"].isna(), "action"] = "HOLD"

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
