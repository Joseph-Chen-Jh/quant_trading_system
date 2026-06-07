"""
数据清洗模块
"""
import pandas as pd
import numpy as np
from loguru import logger


def clean_daily_price(df: pd.DataFrame) -> pd.DataFrame:
    """清洗日线行情数据"""
    if df.empty:
        return df

    df = df.copy()
    # 去除重复
    df = df.drop_duplicates(subset=["ts_code", "trade_date"])

    # 缺失值处理
    numeric_cols = ["open", "high", "low", "close", "volume", "amount"]
    for col in numeric_cols:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce")

    # 剔除全为 NaN 的行
    df = df.dropna(subset=[c for c in numeric_cols if c in df.columns], how="all")

    # 异常值过滤：价格为0或负的剔除
    if "close" in df.columns:
        df = df[df["close"] > 0]

    if "high" in df.columns and "low" in df.columns:
        df = df[df["high"] >= df["low"]]

    # 排序
    df = df.sort_values(["ts_code", "trade_date"]).reset_index(drop=True)

    return df


def clean_stock_basic(df: pd.DataFrame) -> pd.DataFrame:
    """清洗股票基础信息"""
    df = df.copy()
    # 去除退市的
    if "delist_date" not in df.columns:
        df["delist_date"] = None
    df["delist_date"] = pd.to_datetime(df["delist_date"], errors="coerce")
    return df


def fill_missing_dates(df: pd.DataFrame) -> pd.DataFrame:
    """
    补全缺失的交易日 (停牌日前向填充)
    注意：这只针对单只股票的数据
    """
    if df.empty:
        return df
    df = df.copy()
    df["trade_date"] = pd.to_datetime(df["trade_date"])
    df = df.set_index("trade_date")
    idx = pd.date_range(df.index.min(), df.index.max(), freq="B")
    df = df.reindex(idx, method="ffill")
    return df.reset_index().rename(columns={"index": "trade_date"})
