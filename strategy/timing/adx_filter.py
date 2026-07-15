"""
ADX (Average Directional Index) 指标计算

ADX 衡量趋势强度 (不区分方向):
    - ADX > 25: 趋势明显 (上涨或下跌)
    - ADX 20~25: 趋势较弱
    - ADX < 20: 无趋势 (横盘震荡)

计算步骤:
    1. +DM / -DM (方向性移动)
    2. TR (真实波幅)
    3. +DI / -DI (方向性指标) = DM / TR 的平滑值
    4. DX = |+DI - -DI| / (+DI + -DI) * 100
    5. ADX = DX 的平滑平均

参考: Wells Wilder (1978) "New Concepts in Technical Trading Systems"
"""
import pandas as pd
import numpy as np


def calculate_adx(
    data: pd.DataFrame,
    period: int = 14,
    high_col: str = "high",
    low_col: str = "low",
    close_col: str = "close",
) -> pd.DataFrame:
    """
    计算 ADX 指标

    Args:
        data: 日线数据, 必须包含 high, low, close 列
        period: 计算周期 (默认 14, Wilder 标准)
    Returns:
        原 DataFrame 加 adx, plus_di, minus_di 列
    """
    df = data.copy().sort_values("trade_date").reset_index(drop=True)

    high = df[high_col]
    low = df[low_col]
    close = df[close_col]

    # 1. 真实波幅 TR (True Range)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    # 2. 方向性移动 +DM / -DM
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low

    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    plus_dm = pd.Series(plus_dm, index=df.index)

    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    minus_dm = pd.Series(minus_dm, index=df.index)

    # 3. Wilder 平滑 (类似 EMA, alpha = 1/period)
    # 第一个有效值用简单求和, 后续用平滑
    atr = _wilder_smooth(tr, period)
    plus_dm_smooth = _wilder_smooth(plus_dm, period)
    minus_dm_smooth = _wilder_smooth(minus_dm, period)

    # 4. +DI / -DI
    plus_di = 100 * plus_dm_smooth / atr.replace(0, np.nan)
    minus_di = 100 * minus_dm_smooth / atr.replace(0, np.nan)

    # 5. DX
    di_sum = plus_di + minus_di
    di_diff = (plus_di - minus_di).abs()
    dx = 100 * di_diff / di_sum.replace(0, np.nan)

    # 6. ADX = DX 的平滑平均
    adx = _wilder_smooth(dx, period)

    df["adx"] = adx
    df["plus_di"] = plus_di
    df["minus_di"] = minus_di

    return df


def _wilder_smooth(series: pd.Series, period: int) -> pd.Series:
    """
    Wilder 平滑法 (标准实现, 处理前导 NaN):
    - 找到第一个非 NaN 值之后, 取 period 个有效值的平均作为起始
    - 后续值 = (前一个值 × (period-1) + 当前值) / period
    """
    result = pd.Series(np.nan, index=series.index, dtype=float)

    # 找到第一个非 NaN 的位置
    first_valid_idx = series.first_valid_index()
    if first_valid_idx is None:
        return result

    start_pos = series.index.get_loc(first_valid_idx)
    # 从 start_pos 开始, 取 period 个连续有效值
    if start_pos + period > len(series):
        return result

    first_window = series.iloc[start_pos:start_pos + period]
    if not first_window.notna().all():
        return result

    result.iloc[start_pos + period - 1] = first_window.mean()

    # 后续值递推
    for i in range(start_pos + period, len(series)):
        prev = result.iloc[i - 1]
        curr = series.iloc[i]
        if pd.notna(prev) and pd.notna(curr):
            result.iloc[i] = (prev * (period - 1) + curr) / period

    return result


if __name__ == "__main__":
    # 自测: 计算 ADX 并打印
    import sys
    import os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

    from data.storage.database import DataStore

    store = DataStore()
    df = store.load_daily_price(ts_code="000001.SZ", start="20240101")
    print(f"数据: {len(df)} 行")

    df = calculate_adx(df, period=14)
    print("\n最后 10 天 ADX:")
    print(df[["trade_date", "close", "adx", "plus_di", "minus_di"]].tail(10).to_string(index=False))

    # 统计 ADX 分布
    adx_valid = df["adx"].dropna()
    print(f"\nADX 统计:")
    print(f"  均值: {adx_valid.mean():.1f}")
    print(f"  >25 占比: {(adx_valid > 25).mean():.1%}")
    print(f"  >20 占比: {(adx_valid > 20).mean():.1%}")
