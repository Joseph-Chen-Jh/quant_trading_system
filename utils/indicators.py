"""
常用技术指标
"""
import pandas as pd
import numpy as np


def sma(series: pd.Series, period: int) -> pd.Series:
    """简单移动平均"""
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    """指数移动平均"""
    return series.ewm(span=period, adjust=False).mean()


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """相对强弱指标"""
    delta = close.diff()
    gain = delta.where(delta > 0, 0)
    loss = (-delta).where(delta < 0, 0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(close: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    """MACD 指标"""
    dif = ema(close, fast) - ema(close, slow)
    dea = ema(dif, signal)
    macd_bar = 2 * (dif - dea)
    return dif, dea, macd_bar


def bollinger(close: pd.Series, period: int = 20, std_mult: float = 2.0):
    """布林带"""
    mid = sma(close, period)
    std = close.rolling(window=period).std()
    upper = mid + std_mult * std
    lower = mid - std_mult * std
    return upper, mid, lower


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """平均真实波幅"""
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def rolling_return(close: pd.Series, period: int = 20) -> pd.Series:
    """滚动收益率"""
    return close.pct_change(periods=period)


def rolling_volatility(close: pd.Series, period: int = 20) -> pd.Series:
    """滚动波动率 (年化)"""
    returns = close.pct_change()
    return returns.rolling(window=period).std() * np.sqrt(252)
