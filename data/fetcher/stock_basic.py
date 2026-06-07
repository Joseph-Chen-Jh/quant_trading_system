"""
股票基础信息抓取
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


def _retry(func, name: str, max_retries: int = 3, delay: float = 2.0):
    """带重试的函数调用"""
    for attempt in range(1, max_retries + 1):
        try:
            logger.debug(f"尝试 {name} (第 {attempt}/{max_retries} 次)...")
            result = func()
            logger.debug(f"{name} 成功")
            return result
        except Exception as e:
            if attempt < max_retries:
                wait = delay * attempt
                logger.warning(f"{name} 失败 (第 {attempt} 次): {e}, {wait}s 后重试...")
                time.sleep(wait)
            else:
                logger.error(f"{name} 最终失败: {e}")
                raise


def fetch_all_stocks() -> pd.DataFrame:
    """
    获取沪深A股全部股票基础信息
    优先用东方财富实时行情接口 (更稳定), 失败则回退到交易所接口

    Returns:
        DataFrame with columns: ts_code, code, name, market, is_st
    """
    logger.info("抓取全A股股票列表...")

    # ---- 方案1: 东方财富实时行情 (最稳定) ----
    try:
        def _fetch():
            return ak.stock_zh_a_spot_em()
        df = _retry(_fetch, "东方财富A股行情")
        if not df.empty and "代码" in df.columns:
            stocks = pd.DataFrame({
                "code": df["代码"].astype(str).str.zfill(6),
                "name": df["名称"].astype(str),
            })
            stocks["market"] = stocks["code"].apply(
                lambda x: "SH" if x.startswith(("6", "5", "9")) else "SZ"
            )
            stocks["ts_code"] = stocks["code"] + "." + stocks["market"]
            stocks["is_st"] = stocks["name"].str.contains("ST", na=False)
            logger.info(f"方案1 成功: {len(stocks)} 只股票")
            return stocks[["ts_code", "code", "name", "market", "is_st"]]
    except Exception as e:
        logger.warning(f"方案1 失败: {e}, 尝试方案2...")

    # ---- 方案2: AkShare 内置股票列表 ----
    try:
        def _fetch():
            return ak.stock_info_a_code_name()
        df = _retry(_fetch, "AkShare 股票列表")
        if not df.empty and "code" in df.columns:
            stocks = pd.DataFrame({
                "code": df["code"].astype(str).str.zfill(6),
                "name": df["name"].astype(str),
            })
            stocks["market"] = stocks["code"].apply(
                lambda x: "SH" if x.startswith(("6", "5", "9")) else "SZ"
            )
            stocks["ts_code"] = stocks["code"] + "." + stocks["market"]
            stocks["is_st"] = stocks["name"].str.contains("ST", na=False)
            logger.info(f"方案2 成功: {len(stocks)} 只股票")
            return stocks[["ts_code", "code", "name", "market", "is_st"]]
    except Exception as e:
        logger.warning(f"方案2 失败: {e}, 尝试方案3...")

    # ---- 方案3: 上交所 + 深交所分别获取 (原方案) ----
    logger.info("方案3: 分别从交易所获取...")
    all_stocks = []

    # 上交所
    try:
        def _fetch_sh():
            return ak.stock_info_sh_name_code()
        sh = _retry(_fetch_sh, "上交所列表")
        if "证券代码" in sh.columns:
            sh = sh.rename(columns={"证券代码": "code", "证券简称": "name"})
        else:
            sh = sh.rename(columns={sh.columns[0]: "code", sh.columns[1]: "name"})
        sh["market"] = "SH"
        all_stocks.append(sh[["code", "name", "market"]])
        logger.info(f"上交所: {len(sh)} 只")
    except Exception as e:
        logger.error(f"上交所获取失败: {e}")

    # 深交所
    try:
        def _fetch_sz():
            return ak.stock_info_sz_name_code()
        sz = _retry(_fetch_sz, "深交所列表", max_retries=2)
        if "A股代码" in sz.columns:
            sz = sz.rename(columns={"A股代码": "code", "A股简称": "name"})
        else:
            sz = sz.rename(columns={sz.columns[0]: "code", sz.columns[1]: "name"})
        sz["market"] = "SZ"
        all_stocks.append(sz[["code", "name", "market"]])
        logger.info(f"深交所: {len(sz)} 只")
    except Exception as e:
        logger.error(f"深交所获取失败: {e}")

    if not all_stocks:
        raise RuntimeError("所有获取方案均失败，请检查网络连接")

    stocks = pd.concat(all_stocks, ignore_index=True)
    stocks["code"] = stocks["code"].astype(str).str.zfill(6)
    stocks["ts_code"] = stocks["code"] + "." + stocks["market"]
    stocks["is_st"] = stocks["name"].str.contains("ST", na=False)

    logger.info(f"获取到 {len(stocks)} 只股票")
    return stocks[["ts_code", "code", "name", "market", "is_st"]]


def get_stock_pool(
    stocks: pd.DataFrame = None,
    exclude_st: bool = True,
) -> pd.DataFrame:
    """
    获取可交易的股票池

    Args:
        stocks: 全量股票信息
        exclude_st: 是否排除ST股票
    Returns:
        过滤后的股票列表
    """
    if stocks is None:
        stocks = fetch_all_stocks()

    pool = stocks.copy()
    if exclude_st:
        pool = pool[~pool["is_st"]]
    logger.info(f"股票池: {len(pool)} 只 (过滤后)")
    return pool


if __name__ == "__main__":
    df = fetch_all_stocks()
    print(df.head(10))
    print(f"\n共 {len(df)} 只股票")
