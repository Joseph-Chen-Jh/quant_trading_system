"""
KDJ 随机指标策略 (Stochastic Oscillator)

由 George Lane 在 1950 年代提出, 基于价格在近期波动区间的相对位置判断超买超卖:
    - RSV = (Close - Low_N) / (High_N - Low_N) * 100    价格在 N 日区间的相对位置
    - K   = SMA(RSV, M1)                                 RSV 的平滑 (快线)
    - D   = SMA(K, M2)                                   K 的平滑 (慢线, 信号线)
    - J   = 3 * K - 2 * D                                辅助线 (可越界, <0 超卖, >100 超买)

逻辑:
    - 金叉: K 从下方上穿 D, 且 K < oversold_threshold → BUY (超卖区反弹)
    - 死叉: K 从上方下穿 D, 且 K > overbought_threshold → SELL (超买区回落)
    - 其他情况 → HOLD

参数:
    - n_period: RSV 计算的回看窗口 (默认 9, KDJ 标准)
    - m1: K 值的平滑周期 (默认 3, KDJ 标准)
    - m2: D 值的平滑周期 (默认 3, KDJ 标准)
    - oversold_threshold: 超卖阈值 (默认 20), 金叉时 K 必须低于此值
    - overbought_threshold: 超买阈值 (默认 80), 死叉时 K 必须高于此值

可选:
    - use_j_filter: 是否启用 J 线过滤 (默认 False)
        启用时: 买入还需 J < 0 (极度超卖), 卖出还需 J > 100 (极度超买)
        注意: J<0 与金叉(K>D) 存在数学矛盾, 实测会零交易, 不推荐使用
    - multi_period: 是否启用多周期共振 (默认 False)
        启用时: 额外计算长周期 KDJ(long_n_period, 默认 14)
        买入还需长周期 K < 50 (长期仍在弱势), 卖出还需长周期 K > 50 (长期转强)
        类似 RSI 多周期共振的"双重过滤", 逻辑已被 RSI 验证有效

注意:
    - K/D 平滑用 SMA(M1/M2) 而非 Wilder 平滑 (与通达信/同花顺一致)
    - T 日收盘生成信号 → T+1 开盘成交 (由 PortfolioRunner 保证)
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd
import numpy as np
from strategy.base_strategy import BaseStrategy


class KDJStrategy(BaseStrategy):
    """KDJ 超买超卖策略 (均值回归)"""

    def __init__(
        self,
        n_period: int = 9,
        m1: int = 3,
        m2: int = 3,
        oversold_threshold: float = 20.0,
        overbought_threshold: float = 80.0,
        use_j_filter: bool = False,
        multi_period: bool = False,
        long_n_period: int = 14,
    ):
        """
        Args:
            n_period: RSV 计算的回看窗口 (默认 9)
            m1: K 值的平滑周期 (默认 3)
            m2: D 值的平滑周期 (默认 3)
            oversold_threshold: 超卖阈值 (默认 20), 金叉时 K 必须低于此值
            overbought_threshold: 超买阈值 (默认 80), 死叉时 K 必须高于此值
            use_j_filter: 是否启用 J 线过滤 (默认 False, 不推荐)
            multi_period: 是否启用多周期共振 (默认 False)
            long_n_period: 长周期 RSV 回看窗口 (默认 14)
        """
        super().__init__(name="KDJ")
        self.n_period = n_period
        self.m1 = m1
        self.m2 = m2
        self.oversold_threshold = oversold_threshold
        self.overbought_threshold = overbought_threshold
        self.use_j_filter = use_j_filter
        self.multi_period = multi_period
        self.long_n_period = long_n_period
        self.params = {
            "n": n_period,
            "m1": m1,
            "m2": m2,
            "oversold": oversold_threshold,
            "overbought": overbought_threshold,
            "j_filter": use_j_filter,
            "multi_period": multi_period,
            "long_n": long_n_period,
        }

    def _calc_kdj(self, df: pd.DataFrame, n_period: int) -> tuple:
        """
        计算 KDJ 三线 (内部方法, 供主周期和长周期复用)

        Args:
            df: 已排序的 DataFrame, 包含 high, low, close
            n_period: RSV 回看窗口
        Returns:
            (k, d, j) 三个 pd.Series
        """
        # RSV
        low_n = df["low"].rolling(window=n_period, min_periods=n_period).min()
        high_n = df["high"].rolling(window=n_period, min_periods=n_period).max()
        rsv = (df["close"] - low_n) / (high_n - low_n) * 100.0

        k = pd.Series(np.nan, index=df.index)
        d = pd.Series(np.nan, index=df.index)

        first_valid_rsv = rsv.dropna()
        if len(first_valid_rsv) == 0:
            j = 3 * k - 2 * d
            return k, d, j

        first_idx = first_valid_rsv.index[0]
        k.loc[first_idx] = 50.0
        d.loc[first_idx] = 50.0

        for i in range(first_idx + 1, len(df)):
            if pd.notna(rsv.iloc[i]) and pd.notna(k.iloc[i - 1]):
                k.iloc[i] = (self.m1 - 1) / self.m1 * k.iloc[i - 1] + 1.0 / self.m1 * rsv.iloc[i]
            if pd.notna(k.iloc[i]) and pd.notna(d.iloc[i - 1]):
                d.iloc[i] = (self.m2 - 1) / self.m2 * d.iloc[i - 1] + 1.0 / self.m2 * k.iloc[i]

        j = 3 * k - 2 * d
        return k, d, j

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        生成 KDJ 金叉死叉信号

        Args:
            data: 单只股票日线, 必须包含 ts_code, trade_date, high, low, close
        Returns:
            DataFrame with columns:
                ts_code, trade_date, close, k, d, j, action
            action ∈ {BUY, SELL, HOLD}
        """
        required = ["ts_code", "trade_date", "high", "low", "close"]
        for col in required:
            if col not in data.columns:
                raise ValueError(f"输入数据缺少必要列: {col}")

        df = data.sort_values("trade_date").copy().reset_index(drop=True)

        # 主周期 KDJ (默认 9)
        k, d, j = self._calc_kdj(df, self.n_period)

        df["k"] = k
        df["d"] = d
        df["j"] = j

        df["prev_k"] = k.shift(1)
        df["prev_d"] = d.shift(1)

        df["action"] = "HOLD"

        # 金叉: 前一日 K <= D, 今日 K > D
        golden_cross = (df["prev_k"] <= df["prev_d"]) & (df["k"] > df["d"])
        # 死叉: 前一日 K >= D, 今日 K < D
        death_cross = (df["prev_k"] >= df["prev_d"]) & (df["k"] < df["d"])

        # 超卖区过滤: 金叉时 K 必须在超卖区
        golden_cross = golden_cross & (df["k"] < self.oversold_threshold)
        # 超买区过滤: 死叉时 K 必须在超买区
        death_cross = death_cross & (df["k"] > self.overbought_threshold)

        # J 线过滤 (可选, 不推荐 - 与金叉存在数学矛盾)
        if self.use_j_filter:
            golden_cross = golden_cross & (df["j"] < 0)
            death_cross = death_cross & (df["j"] > 100)

        # 多周期共振过滤 (可选): 长周期 K 确认大趋势
        if self.multi_period:
            k_long, d_long, j_long = self._calc_kdj(df, self.long_n_period)
            # 买入需长周期 K < 50 (长期仍在弱势, 真正的底部反弹)
            golden_cross = golden_cross & (k_long < 50)
            # 卖出需长周期 K > 50 (长期已转强, 反弹到位)
            death_cross = death_cross & (k_long > 50)

        df.loc[golden_cross, "action"] = "BUY"
        df.loc[death_cross, "action"] = "SELL"

        # K/D 为 NaN 时 (前 n_period 天), 强制 HOLD
        df.loc[df["k"].isna() | df["d"].isna(), "action"] = "HOLD"

        return df[["ts_code", "trade_date", "close", "k", "d", "j", "action"]]


if __name__ == "__main__":
    from data.storage.database import DataStore

    store = DataStore()
    df = store.load_daily_price(ts_code="000001.SZ", start="20240101")
    print(f"数据: {len(df)} 行")

    strategy = KDJStrategy(n_period=9, m1=3, m2=3)
    signals = strategy.generate_signals(df)

    trades = signals[signals["action"] != "HOLD"]
    print(f"\n信号数: {len(trades)} (BUY={len(trades[trades.action=='BUY'])}, SELL={len(trades[trades.action=='SELL'])})")
    print("\n买卖点:")
    print(trades[["trade_date", "close", "k", "d", "j", "action"]].to_string(index=False))
