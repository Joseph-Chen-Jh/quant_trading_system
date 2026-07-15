"""
双均线交叉择时策略 (MA Cross)

最经典的趋势跟踪策略，适合作为入门第一个策略。

逻辑:
    - 短期均线上穿长期均线 (金叉) → BUY
    - 短期均线下穿长期均线 (死叉) → SELL
    - 其他情况 → HOLD

参数:
    - short_window: 短期均线周期 (默认 5)
    - long_window:  长期均线周期 (默认 20)

注意 (未来函数问题):
    当前实现用 T 日收盘价生成信号，并在 T 日收盘价成交。
    这等价于"看到收盘才决定收盘买"，实盘无法做到。
    最小闭环先接受这个偏差，后续应改为:
      T 日收盘生成信号 → T+1 日开盘价成交
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd
from strategy.base_strategy import BaseStrategy
from strategy.timing.adx_filter import calculate_adx


class MACrossStrategy(BaseStrategy):
    """双均线交叉策略 (可选 ADX 过滤)"""

    def __init__(
        self,
        short_window: int = 5,
        long_window: int = 20,
        adx_threshold: float = 0.0,
        adx_period: int = 14,
    ):
        """
        Args:
            short_window: 短期均线周期
            long_window: 长期均线周期
            adx_threshold: ADX 过滤阈值, 0 表示不过滤.
                > 0 时: 买入信号需 ADX > threshold 才生效 (趋势已形成)
            adx_period: ADX 计算周期 (默认 14, Wilder 标准)
        """
        super().__init__(name="MA_Cross")
        if short_window >= long_window:
            raise ValueError("short_window 必须小于 long_window")
        self.short_window = short_window
        self.long_window = long_window
        self.adx_threshold = adx_threshold
        self.adx_period = adx_period
        self.params = {
            "short": short_window,
            "long": long_window,
            "adx_threshold": adx_threshold,
        }

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        生成均线交叉信号 (可选 ADX 过滤)

        Args:
            data: 单只股票日线，必须包含 ts_code, trade_date, close
                  ADX 过滤需要 high, low, close
        Returns:
            DataFrame with columns:
                ts_code, trade_date, close, ma_short, ma_long, action [, adx]
            action ∈ {BUY, SELL, HOLD}
        """
        required = ["ts_code", "trade_date", "close"]
        if self.adx_threshold > 0:
            required += ["high", "low"]
        for col in required:
            if col not in data.columns:
                raise ValueError(f"输入数据缺少必要列: {col}")

        df = data.sort_values("trade_date").copy().reset_index(drop=True)

        # 计算均线
        df["ma_short"] = df["close"].rolling(self.short_window).mean()
        df["ma_long"] = df["close"].rolling(self.long_window).mean()

        # 差值: 正数表示短均线在上
        df["diff"] = df["ma_short"] - df["ma_long"]
        df["prev_diff"] = df["diff"].shift(1)

        # 信号判定
        df["action"] = "HOLD"

        # 金叉: 前一日 diff <= 0，今日 diff > 0
        golden_cross = (df["prev_diff"] <= 0) & (df["diff"] > 0)
        df.loc[golden_cross, "action"] = "BUY"

        # 死叉: 前一日 diff >= 0，今日 diff < 0
        death_cross = (df["prev_diff"] >= 0) & (df["diff"] < 0)
        df.loc[death_cross, "action"] = "SELL"

        # 前 long_window-1 天均线为 NaN，无法判定，强制 HOLD
        df.loc[df["ma_long"].isna(), "action"] = "HOLD"

        # ADX 过滤: 买入信号需 ADX > threshold
        if self.adx_threshold > 0:
            df = calculate_adx(df, period=self.adx_period)
            # ADX 为 NaN 时 (前 2*period 天), 不允许买入
            weak_trend = df["adx"].fillna(0) <= self.adx_threshold
            # 只过滤 BUY, SELL 不变 (止损/退出不依赖趋势强度)
            df.loc[weak_trend & (df["action"] == "BUY"), "action"] = "HOLD"

        cols = ["ts_code", "trade_date", "close", "ma_short", "ma_long", "action"]
        if "adx" in df.columns:
            cols.append("adx")
        return df[cols]


if __name__ == "__main__":
    # 快速自测: 从数据库拉平安银行，生成信号
    import sys
    import os
    # 必须在导入项目包之前把项目根目录加入 path

    from data.storage.database import DataStore

    store = DataStore()
    df = store.load_daily_price(ts_code="000001.SZ", start="20240101")
    print(f"数据: {len(df)} 行")

    strategy = MACrossStrategy(short_window=5, long_window=20)
    signals = strategy.generate_signals(df)

    # 打印所有买卖信号
    trades = signals[signals["action"] != "HOLD"]
    print(f"\n信号数: {len(trades)} (BUY={len(trades[trades.action=='BUY'])}, SELL={len(trades[trades.action=='SELL'])})")
    print("\n买卖点:")
    print(trades[["trade_date", "close", "ma_short", "ma_long", "action"]].to_string(index=False))
