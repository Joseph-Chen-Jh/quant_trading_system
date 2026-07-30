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
    # 去除重复 (兼容单只股票数据无 ts_code 的情况)
    dup_cols = [c for c in ["ts_code", "trade_date"] if c in df.columns]
    if dup_cols:
        df = df.drop_duplicates(subset=dup_cols)

    # 缺失值处理
    numeric_cols = ["open", "high", "low", "close", "volume", "amount", "turnover"]
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
    sort_cols = [c for c in ["ts_code", "trade_date"] if c in df.columns]
    if sort_cols:
        df = df.sort_values(sort_cols).reset_index(drop=True)
    else:
        df = df.reset_index(drop=True)

    return df


def clean_stock_basic(df: pd.DataFrame) -> pd.DataFrame:
    """清洗股票基础信息

    fetcher 返回字段: ts_code, code, name, market, is_st
    """
    if df.empty:
        return df
    df = df.copy()
    # 去重 (按 ts_code)
    if "ts_code" in df.columns:
        df = df.drop_duplicates(subset=["ts_code"])
    # 代码补零 (akshare 偶尔返回 int)
    if "code" in df.columns:
        df["code"] = df["code"].astype(str).str.zfill(6)
    # is_st: bool -> int (SQLite 无原生 bool)
    if "is_st" in df.columns:
        df["is_st"] = df["is_st"].astype(bool).astype(int)
    return df.reset_index(drop=True)


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
