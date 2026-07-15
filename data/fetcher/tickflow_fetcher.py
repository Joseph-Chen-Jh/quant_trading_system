"""
TickFlow 数据源封装

作为 akshare 的 fallback, 当 akshare 被限流时自动切换。

特点:
  - 免费层无需注册, 支持日K线和批量拉取
  - 不会被限流/封 IP
  - 返回格式与 stock_daily.py 完全一致 (ts_code, trade_date YYYYMMDD 格式)

参考: https://docs.tickflow.org
"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
from datetime import datetime
from loguru import logger

try:
    from tickflow import TickFlow
    _tf = None  # 懒加载单例
except ImportError:
    _tf = None
    logger.warning("tickflow 未安装, fallback 功能不可用。安装: pip install \"tickflow[all]\"")


def _get_client():
    """懒加载 TickFlow 免费客户端"""
    global _tf
    if _tf is None:
        try:
            _tf = TickFlow.free()
        except Exception as e:
            logger.error(f"TickFlow 初始化失败: {e}")
            return None
    return _tf


def fetch_single_stock_by_ts_code(
    ts_code: str,
    start_date: str = "20200101",
    count: int = 5000,
) -> pd.DataFrame:
    """
    通过 ts_code 获取日线 (TickFlow 免费层)

    Args:
        ts_code:    股票代码 (000001.SZ / 600001.SH)
        start_date: 起始日期 YYYYMMDD (本地过滤, TickFlow 用 count 拉取)
        count:      拉取最近 N 根 K 线 (5000 约覆盖 20 年, 足够)
    Returns:
        DataFrame: ts_code, trade_date(YYYYMMDD), open, high, low, close, volume, amount
    """
    tf = _get_client()
    if tf is None:
        return pd.DataFrame()

    try:
        df = tf.klines.get(
            ts_code,
            period="1d",
            count=count,
            as_dataframe=True,
        )
    except Exception as e:
        logger.error(f"TickFlow 拉取 {ts_code} 失败: {e}")
        return pd.DataFrame()

    if df is None or df.empty:
        return pd.DataFrame()

    # 列名转换: TickFlow 用 symbol, 我们用 ts_code
    if "symbol" in df.columns:
        df = df.rename(columns={"symbol": "ts_code"})

    # 日期格式转换: TickFlow 返回 '2026-01-30', 我们用 '20260130'
    if "trade_date" in df.columns:
        df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")

    # 本地按 start_date 过滤
    df = df[df["trade_date"] >= start_date].copy()

    # 只保留需要的列
    keep = ["ts_code", "trade_date", "open", "high", "low", "close", "volume", "amount"]
    keep = [c for c in keep if c in df.columns]
    df = df[keep]

    # 按日期升序
    df = df.sort_values("trade_date").reset_index(drop=True)
    return df


def fetch_batch(
    ts_codes: list,
    start_date: str = "20200101",
    count: int = 5000,
    show_progress: bool = True,
) -> pd.DataFrame:
    """
    批量拉取多只股票日线 (TickFlow 免费层支持)

    Args:
        ts_codes:   ts_code 列表
        start_date: 起始日期 (本地过滤)
        count:      每只股票拉取最近 N 根 K 线
        show_progress: 是否显示进度条
    Returns:
        合并后的 DataFrame
    """
    tf = _get_client()
    if tf is None:
        return pd.DataFrame()

    try:
        dfs = tf.klines.batch(
            ts_codes,
            period="1d",
            count=count,
            as_dataframe=True,
            show_progress=show_progress,
        )
    except Exception as e:
        logger.error(f"TickFlow 批量拉取失败: {e}")
        return pd.DataFrame()

    if not dfs:
        return pd.DataFrame()

    all_data = []
    for ts_code, df in dfs.items():
        if df is None or df.empty:
            continue

        if "symbol" in df.columns:
            df = df.rename(columns={"symbol": "ts_code"})

        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")

        df = df[df["trade_date"] >= start_date].copy()

        keep = ["ts_code", "trade_date", "open", "high", "low", "close", "volume", "amount"]
        keep = [c for c in keep if c in df.columns]
        df = df[keep]
        all_data.append(df)

    if not all_data:
        return pd.DataFrame()

    result = pd.concat(all_data, ignore_index=True)
    result = result.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)
    logger.info(f"TickFlow 批量拉取完成: {len(result)} 行, {result['ts_code'].nunique()} 只股票")
    return result


def get_universe() -> list:
    """获取全 A 股标的池 (ts_code 列表)"""
    tf = _get_client()
    if tf is None:
        return []

    try:
        universe = tf.universes.get("CN_Equity_A")
        return universe.get("symbols", [])
    except Exception as e:
        logger.error(f"TickFlow 获取标的池失败: {e}")
        return []


if __name__ == "__main__":
    # 自测
    print("=== 单只股票测试 ===")
    df = fetch_single_stock_by_ts_code("000001.SZ", start_date="20240101")
    print(f"行数: {len(df)}")
    print(f"列名: {df.columns.tolist()}")
    print(df.head(3))
    print(df.tail(3))

    print("\n=== 批量测试 ===")
    df = fetch_batch(["000001.SZ", "300750.SZ"], start_date="20240101", show_progress=False)
    print(f"行数: {len(df)}")
    print(df.groupby("ts_code").size())

    print("\n=== 标的池测试 ===")
    symbols = get_universe()
    print(f"全 A 股: {len(symbols)} 只")
    print(f"前 5: {symbols[:5]}")
