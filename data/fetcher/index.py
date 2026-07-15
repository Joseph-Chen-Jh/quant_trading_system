"""
指数日线数据抓取

覆盖: 沪深300、上证50、中证500、创业板指、科创50
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import pandas as pd
from loguru import logger

try:
    import akshare as ak
except ImportError:
    logger.error("请先安装 akshare: pip install akshare")
    raise


# 常用指数映射: ts_code -> (akshare symbol, 名称)
INDEX_MAP = {
    "000300.SH": ("000300", "沪深300"),
    "000016.SH": ("000016", "上证50"),
    "000905.SH": ("000905", "中证500"),
    "399006.SZ": ("399006", "创业板指"),
    "000688.SH": ("000688", "科创50"),
    "000001.SH": ("000001", "上证指数"),
    "399001.SZ": ("399001", "深证成指"),
    "000852.SH": ("000852", "中证1000"),
}


def fetch_index_daily(
    index_code: str,
    start_date: str = "20150101",
    end_date: str = None,
) -> pd.DataFrame:
    """
    获取指数日线数据

    Args:
        index_code: 指数代码 (如 '000300' 或 '000300.SH')
        start_date: 起始日期 YYYYMMDD
        end_date:   结束日期, 默认今天
    Returns:
        DataFrame: trade_date, open, high, low, close, volume, amount
    """
    from datetime import datetime
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    # 去掉后缀
    symbol = index_code.replace(".SH", "").replace(".SZ", "")

    try:
        df = ak.stock_zh_index_daily(symbol=f"sz{symbol}" if _is_sz(index_code) else f"sh{symbol}")
    except Exception:
        try:
            # 回退: 用另一个接口
            df = ak.index_zh_a_hist(
                symbol=symbol,
                period="daily",
                start_date=start_date,
                end_date=end_date,
            )
        except Exception as e:
            logger.error(f"获取指数 {index_code} 失败: {e}")
            return pd.DataFrame()

    if df.empty:
        return df

    # 标准化列名 (兼容中英文)
    # - ak.stock_zh_index_daily 返回英文列名: date/open/high/low/close/volume
    # - ak.index_zh_a_hist      返回中文列名: 日期/开盘/最高/最低/收盘/成交量/成交额
    rename_map = {
        "date": "trade_date", "日期": "trade_date",
        "open": "open", "开盘": "open",
        "high": "high", "最高": "high",
        "low": "low", "最低": "low",
        "close": "close", "收盘": "close",
        "volume": "volume", "成交量": "volume",
        "amount": "amount", "成交额": "amount",
    }
    # 只保留实际存在的列，避免重命名不存在的列时被 pandas 警告
    actual_rename = {k: v for k, v in rename_map.items() if k in df.columns}
    df = df.rename(columns=actual_rename)

    if "trade_date" not in df.columns:
        logger.warning(f"指数 {index_code} 返回数据缺少日期列，原始列: {list(df.columns)}")
        return pd.DataFrame()

    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
    df["ts_code"] = index_code
    return df


def fetch_all_indices(
    start_date: str = "20150101",
    end_date: str = None,
) -> pd.DataFrame:
    """
    批量获取所有常用指数的日线数据

    Returns:
        合并后的 DataFrame
    """
    all_data = []
    for ts_code, (_, name) in INDEX_MAP.items():
        logger.info(f"抓取 {name} ({ts_code})...")
        df = fetch_index_daily(ts_code, start_date, end_date)
        if not df.empty:
            all_data.append(df)

    if not all_data:
        return pd.DataFrame()

    result = pd.concat(all_data, ignore_index=True)
    logger.info(f"指数数据抓取完成: {len(result)} 行")
    return result


def _is_sz(code: str) -> bool:
    """判断是否是深市指数"""
    return code.startswith("399") or code.endswith(".SZ")


if __name__ == "__main__":
    df = fetch_index_daily("000300.SH", start_date="20250101")
    print(df.head())
    print(f"\n共 {len(df)} 条")
