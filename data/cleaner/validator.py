"""
数据校验模块
"""
import pandas as pd
from loguru import logger


def validate_daily_price(df: pd.DataFrame) -> dict:
    """校验日线数据的完整性"""
    report = {
        "total_rows": len(df),
        "total_stocks": df["ts_code"].nunique() if "ts_code" in df.columns else 0,
        "date_range": None,
        "missing_values": {},
        "anomalies": [],
        "passed": True,
    }

    if df.empty:
        report["passed"] = False
        report["anomalies"].append("数据为空")
        return report

    # 日期范围
    if "trade_date" in df.columns:
        report["date_range"] = (str(df["trade_date"].min()), str(df["trade_date"].max()))

    # 缺失值统计
    for col in df.columns:
        n_missing = df[col].isna().sum()
        if n_missing > 0:
            report["missing_values"][col] = int(n_missing)

    # 价格合理性
    if "close" in df.columns:
        neg_count = (df["close"] <= 0).sum()
        if neg_count > 0:
            report["anomalies"].append(f"{neg_count} 条收盘价 <= 0")
            report["passed"] = False

    if "high" in df.columns and "low" in df.columns:
        invalid = (df["high"] < df["low"]).sum()
        if invalid > 0:
            report["anomalies"].append(f"{invalid} 条最高价 < 最低价")
            report["passed"] = False

    # 涨跌停异常检查 (A股 ±10%)
    if "pre_close" in df.columns and "close" in df.columns:
        change = (df["close"] - df["pre_close"]) / df["pre_close"]
        extreme = (change.abs() > 0.11).sum()
        if extreme > 0:
            report["anomalies"].append(f"{extreme} 条涨跌幅超过 ±11% (可能含新股首日)")
            # 不判为失败，因为新股首日无涨跌停

    return report


def validate_stock_pool(stocks: pd.DataFrame) -> dict:
    """校验股票池"""
    report = {
        "total": len(stocks),
        "duplicated_codes": int(stocks.duplicated(subset=["ts_code"]).sum()) if "ts_code" in stocks.columns else 0,
        "passed": True,
    }
    if report["duplicated_codes"] > 0:
        report["passed"] = False
    return report
