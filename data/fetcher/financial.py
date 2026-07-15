"""
财务数据抓取

覆盖: 利润表、资产负债表关键指标
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import time
import pandas as pd
from loguru import logger

try:
    import akshare as ak
except ImportError:
    logger.error("请先安装 akshare: pip install akshare")
    raise

from config.settings import AKSHARE_REQUEST_INTERVAL


def fetch_financial_indicator(
    ts_code: str,
) -> pd.DataFrame:
    """
    获取单只股票的核心财务指标

    Args:
        ts_code: 如 '000001.SZ'
    Returns:
        DataFrame with columns: ts_code, end_date, roe, eps, revenue, profit, pe, pb ...
    """
    symbol = ts_code.split(".")[0]

    try:
        df = ak.stock_financial_abstract(symbol=symbol)
    except Exception as e:
        logger.warning(f"获取 {ts_code} 财务数据失败: {e}")
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # 不同版本 akshare 返回列名可能不同，做兼容
    df["ts_code"] = ts_code
    return df


def fetch_valuation(
    ts_code: str,
) -> pd.DataFrame:
    """
    获取估值指标 (PE, PB, PS)

    Args:
        ts_code: 如 '000001.SZ'
    Returns:
        DataFrame with columns: trade_date, pe, pb, ps, pcf
    """
    symbol = ts_code.split(".")[0]

    try:
        # 尝试用 stock_a_lg_indicator 获取
        df = ak.stock_a_lg_indicator(symbol=symbol)
    except Exception:
        try:
            df = ak.stock_zh_valuation_baidu(symbol=symbol, period="近五年")
        except Exception as e:
            logger.warning(f"获取 {ts_code} 估值数据失败: {e}")
            return pd.DataFrame()

    if df.empty:
        return df
    df["ts_code"] = ts_code
    return df


def fetch_financial_summary(
    symbols: list,
    delay: float = None,
) -> pd.DataFrame:
    """
    批量获取财务摘要指标 (核心指标快速版)

    使用 stock_yjbb_em (东方财富业绩报表) 一次性拉取全市场，
    本地按 symbols 过滤，避免循环内重复请求导致 IP 被封。

    Args:
        symbols: ts_code 列表
        delay:   已弃用，保留参数为兼容旧调用
    Returns:
        DataFrame 包含 ts_code 及业绩报表原始字段
    """
    if not symbols:
        return pd.DataFrame()

    logger.info(f"批量获取 {len(symbols)} 只股票财务数据 (单次全市场拉取)...")

    try:
        df = ak.stock_yjbb_em(date=None)
    except Exception as e:
        logger.error(f"获取业绩报表失败: {e}")
        return pd.DataFrame()

    if df.empty:
        return pd.DataFrame()

    # 本地过滤: ts_code -> 纯数字 code
    code_set = {s.split(".")[0] for s in symbols}
    df_filtered = df[df["股票代码"].astype(str).isin(code_set)].copy()
    if df_filtered.empty:
        logger.warning("财务数据未匹配到任何股票")
        return pd.DataFrame()

    # 补 ts_code
    code_to_ts = {s.split(".")[0]: s for s in symbols}
    df_filtered["ts_code"] = df_filtered["股票代码"].astype(str).map(code_to_ts)

    logger.info(f"财务数据匹配: {len(df_filtered)}/{len(symbols)} 只")
    return df_filtered.reset_index(drop=True)


def get_latest_financial_snapshot(
    stocks: pd.DataFrame,
) -> pd.DataFrame:
    """
    获取全市场最新财务快照

    使用 akshare 的 stock_individual_info_em 获取个股概要信息

    Args:
        stocks: 包含 ts_code 列的股票列表
    Returns:
        包含 pe, pb, total_mv, circ_mv 的快照 DataFrame
    """
    logger.info("获取全市场财务快照...")
    results = []

    for i, row in stocks.iterrows():
        ts_code = row["ts_code"]
        symbol = ts_code.split(".")[0]

        try:
            info = ak.stock_individual_info_em(symbol=symbol)
            if not info.empty:
                record = {"ts_code": ts_code}
                # 提取关键字段
                for _, item in info.iterrows():
                    key = item["item"]
                    val = item["value"]
                    if key in ("市盈率-动态", "市盈率(动)"):
                        record["pe"] = _safe_float(val)
                    elif key in ("市净率", "市净率(静)"):
                        record["pb"] = _safe_float(val)
                    elif key in ("总市值", "总市值(亿)"):
                        record["total_mv"] = _safe_float(val)
                    elif key in ("流通市值", "流通市值(亿)"):
                        record["circ_mv"] = _safe_float(val)
                    elif key in ("营业收入", "主营收入(亿)"):
                        record["revenue"] = _safe_float(val)
                    elif key in ("净利润", "净利润(亿)"):
                        record["profit"] = _safe_float(val)
                results.append(record)
        except Exception:
            pass

        time.sleep(AKSHARE_REQUEST_INTERVAL)

        if (i + 1) % 100 == 0:
            logger.info(f"快照进度: {i+1}/{len(stocks)}")

    df = pd.DataFrame(results)
    logger.info(f"财务快照完成: {len(df)} 只股票")
    return df


def _safe_float(val):
    """安全转换为浮点数"""
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


if __name__ == "__main__":
    # 测试：单只股票快照
    info = ak.stock_individual_info_em(symbol="000001")
    print(info)
