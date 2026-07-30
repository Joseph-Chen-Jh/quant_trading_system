"""
三均线金叉 + 放量确认策略 (MA Triple Cross + Volume)

均线多头排列形成 + 成交量放大确认趋势启动:
    - 买入: 近 N 天内 MA(5)/MA(10)/MA(20) 三组金叉全部发生 + 当日放量
    - 卖出: 筹码分散止损 — 当日 90%集中度 >= 持仓期间最小集中度的 2 倍

买入条件 (4 个全部满足):
    1. 近 recent_days 天内 MA(5) 上穿 MA(10)
    2. 近 recent_days 天内 MA(5) 上穿 MA(20)
    3. 近 recent_days 天内 MA(10) 上穿 MA(20)
    4. 当日成交量 > 前 vol_lookback 天中任意一天的成交量 (放量确认)

"近 recent_days 天内" 的含义:
    以今日 T 为基准, [T-recent_days+1, ..., T] 这个窗口内发生过金叉即可
    (不要求今日就是金叉日, 允许金叉发生在前几天)

"当日成交量超过前面5天中任意一天":
    volume[T] > max(volume[T-1], ..., volume[T-5])
    即当日成交量 > 前 vol_lookback 天的最大成交量

卖出条件 (筹码分散止损):
    从买入当天起, 记录后续每日的 90%集中度到 concentration_90_list.
    当某日 90%集中度 >= 2 × min(concentration_90_list) 时卖出.
    (集中度从低位翻倍意味着筹码从集中变分散, 主力可能出货)

参数:
    - short_window: 短期均线 (默认 5)
    - mid_window: 中期均线 (默认 10)
    - long_window: 长期均线 (默认 20)
    - recent_days: 金叉窗口 (默认 3, 近3天内)
    - vol_lookback: 成交量回看天数 (默认 5)

注意:
    T 日收盘生成信号 → T+1 开盘成交 (由 PortfolioRunner 保证)
    concentration_90 数据由 data/processor/chip_distribution.py 估算, 存于 chip_distribution 表
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd
import numpy as np
from loguru import logger
from strategy.base_strategy import BaseStrategy


class MAVolumeStrategy(BaseStrategy):
    """三均线金叉 + 放量确认策略 (筹码集中度止损)"""

    def __init__(
        self,
        short_window: int = 5,
        mid_window: int = 10,
        long_window: int = 20,
        recent_days: int = 3,
        vol_lookback: int = 5,
        concentration_multiple: float = 2.0,
    ):
        """
        Args:
            short_window: 短期均线周期 (默认 5)
            mid_window: 中期均线周期 (默认 10)
            long_window: 长期均线周期 (默认 20)
            recent_days: 金叉窗口, 近 N 天内发生过金叉即算 (默认 3)
            vol_lookback: 成交量回看天数, 当日量需超过前 N 天最大量 (默认 5)
            concentration_multiple: 筹码分散卖出阈值倍数 (默认 2.0,
                当日集中度 >= 最小值 × 此倍数时卖出)
        """
        super().__init__(name="MA_Volume")
        self.short_window = short_window
        self.mid_window = mid_window
        self.long_window = long_window
        self.recent_days = recent_days
        self.vol_lookback = vol_lookback
        self.concentration_multiple = concentration_multiple
        self.params = {
            "short": short_window,
            "mid": mid_window,
            "long": long_window,
            "recent_days": recent_days,
            "vol_lookback": vol_lookback,
            "concentration_multiple": concentration_multiple,
        }

    def _detect_golden_cross(self, df: pd.DataFrame, fast_col: str, slow_col: str) -> pd.Series:
        """检测金叉 (今日快线上穿慢线: 昨日 diff<=0, 今日 diff>0)"""
        diff = df[fast_col] - df[slow_col]
        prev_diff = diff.shift(1)
        return (prev_diff <= 0) & (diff > 0)

    def _recent_cross(self, cross_series: pd.Series, window: int) -> pd.Series:
        """检测近 window 天内是否发生过金叉 (含今日)"""
        return cross_series.astype(int).rolling(window=window, min_periods=1).max().astype(bool)

    def _load_concentration_90(self, df: pd.DataFrame) -> pd.Series:
        """从 chip_distribution 表加载 90%集中度, 对齐到 df 的 trade_date

        若 df 已含 concentration_90 列则直接返回; 否则查库.
        查不到数据时返回全 NaN (卖出条件无法触发, 等价于不设止损).
        """
        if "concentration_90" in df.columns:
            return df["concentration_90"]

        ts_code = df["ts_code"].iloc[0] if len(df) > 0 else None
        if ts_code is None:
            return pd.Series(np.nan, index=df.index)

        try:
            from data.storage.database import DataStore
            store = DataStore()
            chip_df = store.load_chip_distribution(ts_code=ts_code)
            if chip_df.empty:
                logger.warning(f"{ts_code}: chip_distribution 表无数据, 筹码止损不生效")
                return pd.Series(np.nan, index=df.index)
            merged = df[["trade_date"]].merge(
                chip_df[["trade_date", "concentration_90"]],
                on="trade_date", how="left",
            )
            return merged["concentration_90"]
        except Exception as e:
            logger.warning(f"{ts_code}: 加载 concentration_90 失败: {e}, 筹码止损不生效")
            return pd.Series(np.nan, index=df.index)

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        生成买入/卖出信号

        买入: 三均线金叉 + 放量 (4 条件同时满足)
        卖出: 筹码分散止损 — 当日 concentration_90 >= concentration_multiple × min(持仓期间列表)

        Args:
            data: 单只股票日线, 必须包含 ts_code, trade_date, close, volume
                  (可选 concentration_90 列; 若无则自动从 chip_distribution 表加载)
        Returns:
            DataFrame with columns:
                ts_code, trade_date, close, ma_short, ma_mid, ma_long,
                concentration_90, action
            action ∈ {BUY, SELL, HOLD}
        """
        required = ["ts_code", "trade_date", "close", "volume"]
        for col in required:
            if col not in data.columns:
                raise ValueError(f"输入数据缺少必要列: {col}")

        df = data.sort_values("trade_date").copy().reset_index(drop=True)

        # 计算三条均线
        df["ma_short"] = df["close"].rolling(self.short_window).mean()
        df["ma_mid"] = df["close"].rolling(self.mid_window).mean()
        df["ma_long"] = df["close"].rolling(self.long_window).mean()

        # 三组金叉检测
        gc_5_10 = self._detect_golden_cross(df, "ma_short", "ma_mid")
        gc_5_20 = self._detect_golden_cross(df, "ma_short", "ma_long")
        gc_10_20 = self._detect_golden_cross(df, "ma_mid", "ma_long")

        # 近 recent_days 天内是否发生过金叉
        recent_gc_5_10 = self._recent_cross(gc_5_10, self.recent_days)
        recent_gc_5_20 = self._recent_cross(gc_5_20, self.recent_days)
        recent_gc_10_20 = self._recent_cross(gc_10_20, self.recent_days)

        # 成交量条件: 当日成交量 > 前 vol_lookback 天的最大成交量
        df["prev_vol_max"] = df["volume"].shift(1).rolling(self.vol_lookback).max()
        vol_confirm = df["volume"] > df["prev_vol_max"]

        # 买入信号: 4 个条件全部满足
        buy_signal = (recent_gc_5_10 & recent_gc_5_20
                      & recent_gc_10_20 & vol_confirm)

        # 加载 90%集中度
        df["concentration_90"] = self._load_concentration_90(df)

        # ===== 状态机遍历: 买入后跟踪 concentration_90_list =====
        # 卖出条件: 当日 concentration_90 >= concentration_multiple × min(list)
        #   - 买入当天: concentration_90 入 list 作为基准
        #   - 后续每日: 先判断是否触发卖出, 未触发则追加到 list
        #   - concentration_90 为 NaN 的日期: 不追加, 不判断 (跳过)
        concentration_90_list = []
        in_position = False
        actions = []

        for i in range(len(df)):
            buy = bool(buy_signal.iloc[i])
            conc90 = df["concentration_90"].iloc[i]
            ma_long_valid = pd.notna(df["ma_long"].iloc[i])

            # 均线预热期强制 HOLD
            if not ma_long_valid:
                actions.append("HOLD")
                continue

            if in_position:
                # 持仓中: 检查筹码分散卖出条件
                if pd.notna(conc90) and concentration_90_list:
                    # 当天集中度 >= 最小值的 N 倍 → 筹码分散, 卖出
                    min_conc = min(concentration_90_list)
                    if conc90 >= min_conc * self.concentration_multiple:
                        actions.append("SELL")
                        in_position = False
                        concentration_90_list = []
                        continue
                # 未触发卖出, 追加当天集中度到列表
                if pd.notna(conc90):
                    concentration_90_list.append(float(conc90))
                actions.append("HOLD")
            else:
                # 空仓: 检查买入信号
                if buy:
                    actions.append("BUY")
                    in_position = True
                    # 买入当天 concentration_90 入列表作为基准
                    concentration_90_list = (
                        [float(conc90)] if pd.notna(conc90) else []
                    )
                else:
                    actions.append("HOLD")

        df["action"] = actions

        return df[[
            "ts_code", "trade_date", "close",
            "ma_short", "ma_mid", "ma_long",
            "concentration_90", "action",
        ]]


if __name__ == "__main__":
    from data.storage.database import DataStore

    store = DataStore()
    df = store.load_daily_price(ts_code="000001.SZ", start="20240101")
    print(f"数据: {len(df)} 行")

    strategy = MAVolumeStrategy(short_window=5, mid_window=10, long_window=20, recent_days=3, vol_lookback=5)
    signals = strategy.generate_signals(df)

    trades = signals[signals["action"] != "HOLD"]
    n_buy = len(trades[trades.action == "BUY"])
    n_sell = len(trades[trades.action == "SELL"])
    print(f"\n信号数: {len(trades)} (BUY={n_buy}, SELL={n_sell})")
    print("\n买卖点:")
    print(trades[["trade_date", "close", "ma_short", "ma_mid", "ma_long",
                   "concentration_90", "action"]].to_string(index=False))
