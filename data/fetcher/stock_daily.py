"""
A股日线行情数据抓取

支持:
  - 单只股票历史日线
  - 批量全市场抓取（带频率控制）
  - 增量更新
  - akshare 失败时自动 fallback 到 TickFlow 免费层
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import time
import pandas as pd
from datetime import datetime, timedelta
from loguru import logger

try:
    import akshare as ak
except ImportError:
    logger.error("请先安装 akshare: pip install akshare")
    raise

from config.settings import AKSHARE_REQUEST_INTERVAL

# TickFlow fallback (可选依赖, 未装时静默跳过)
try:
    from data.fetcher import tickflow_fetcher as _tickflow
    _tickflow_available = True
except ImportError:
    _tickflow = None
    _tickflow_available = False


def _retry(func, name: str, max_retries: int = 3, delay: float = 2.0):
    """带重试的函数调用"""
    for attempt in range(1, max_retries + 1):
        try:
            return func()
        except Exception as e:
            if attempt < max_retries:
                wait = delay * attempt
                logger.warning(f"{name} 失败 (第 {attempt} 次): {e}, {wait}s 后重试...")
                time.sleep(wait)
            else:
                logger.error(f"{name} 最终失败: {e}")
                raise


def fetch_single_stock(
    symbol: str,
    start_date: str = "20200101",
    end_date: str = None,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """
    获取单只股票日线数据

    Args:
        symbol:   纯数字代码，如 '000001' (不带 .SH/.SZ)
        start_date: 起始日期 YYYYMMDD
        end_date:   结束日期 YYYYMMDD, 默认今天
        adjust:     'qfq' 前复权 / 'hfq' 后复权 / '' 不复权
    Returns:
        DataFrame: trade_date, open, high, low, close, volume, amount
    """
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    try:
        df = _retry(
            lambda: ak.stock_zh_a_hist(
                symbol=symbol, period="daily",
                start_date=start_date, end_date=end_date, adjust=adjust,
            ),
            f"日线 {symbol}",
            max_retries=2,
        )
    except Exception as e:
        logger.error(f"获取 {symbol} 失败: {e}")
        return pd.DataFrame()

    if df.empty:
        return df

    df = df.rename(columns={
        "日期": "trade_date",
        "开盘": "open",
        "收盘": "close",
        "最高": "high",
        "最低": "low",
        "成交量": "volume",
        "成交额": "amount",
        "振幅": "amplitude",
        "涨跌幅": "pct_chg",
        "涨跌额": "change",
        "换手率": "turnover",
    })

    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
    return df


def fetch_single_stock_by_ts_code(
    ts_code: str,
    start_date: str = "20200101",
    end_date: str = None,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """
    通过 ts_code (如 000001.SZ) 获取日线

    优先用 akshare, 失败(限流/空数据)时自动切换 TickFlow 免费层.

    Args:
        ts_code: 股票代码 (000001.SZ / 600001.SH)
    """
    symbol = ts_code.split(".")[0]
    df = fetch_single_stock(symbol, start_date, end_date, adjust)
    if not df.empty:
        df["ts_code"] = ts_code
        return df

    # akshare 失败 → 尝试 TickFlow fallback
    if not _tickflow_available:
        return df  # 返回空 DataFrame

    logger.info(f"{ts_code} akshare 失败, 尝试 TickFlow fallback...")
    tf_df = _tickflow.fetch_single_stock_by_ts_code(
        ts_code, start_date=start_date, count=5000
    )
    if not tf_df.empty:
        logger.info(f"{ts_code} TickFlow fallback 成功: {len(tf_df)} 行")
    return tf_df


def fetch_batch(
    codes: list,
    start_date: str = "20200101",
    end_date: str = None,
    adjust: str = "qfq",
    delay: float = None,
) -> pd.DataFrame:
    """
    批量抓取多只股票日线

    优先 akshare 逐只抓, 失败的 ts_code 在最后用 TickFlow 批量补齐.

    Args:
        codes:      ts_code 列表，如 ['000001.SZ', '600001.SH']
        start_date: 起始日期
        end_date:   结束日期
        adjust:     复权方式
        delay:      请求间隔(秒)，默认取全局配置
    Returns:
        合并后的 DataFrame
    """
    if delay is None:
        delay = AKSHARE_REQUEST_INTERVAL

    all_data = []
    failed_codes = []
    total = len(codes)

    for i, ts_code in enumerate(codes):
        symbol = ts_code.split(".")[0]

        try:
            df = fetch_single_stock(symbol, start_date, end_date, adjust)
            if not df.empty:
                df["ts_code"] = ts_code
                all_data.append(df)
            else:
                failed_codes.append(ts_code)

            if (i + 1) % 50 == 0:
                logger.info(f"进度: {i+1}/{total} (失败 {len(failed_codes)})")

        except Exception as e:
            logger.warning(f"跳过 {ts_code}: {e}")
            failed_codes.append(ts_code)

        time.sleep(delay)

    # akshare 失败的股票 → TickFlow 批量补齐
    if failed_codes and _tickflow_available:
        logger.info(f"akshare 失败 {len(failed_codes)} 只, 用 TickFlow 批量补齐...")
        tf_df = _tickflow.fetch_batch(
            failed_codes, start_date=start_date, count=5000, show_progress=False
        )
        if not tf_df.empty:
            all_data.append(tf_df)
            logger.info(f"TickFlow 补齐成功: {len(tf_df)} 行, "
                        f"{tf_df['ts_code'].nunique()} 只股票")

    if not all_data:
        logger.warning("未获取到任何数据 (akshare + TickFlow 均失败)")
        return pd.DataFrame()

    result = pd.concat(all_data, ignore_index=True)
    # 去重: 同一 (ts_code, trade_date) 优先保留先到的 (akshare)
    if "ts_code" in result.columns and "trade_date" in result.columns:
        result = result.drop_duplicates(subset=["ts_code", "trade_date"], keep="first")
    logger.info(f"批量抓取完成: {len(result)} 行, {result['ts_code'].nunique()} 只股票")
    return result


def fetch_daily_increment(
    codes: list,
    date: str = None,
    adjust: str = "qfq",
) -> pd.DataFrame:
    """
    增量抓取 — 只抓最近一天数据

    Args:
        codes: ts_code 列表
        date:  目标日期 YYYYMMDD，默认上一个交易日
    Returns:
        当日行情 DataFrame
    """
    if date is None:
        date = _last_trade_date()

    logger.info(f"增量抓取 {date} 数据, {len(codes)} 只股票...")
    return fetch_batch(codes, start_date=date, end_date=date, adjust=adjust)


def _last_trade_date() -> str:
    """获取上一个交易日"""
    today = datetime.now()
    # 如果当前时间在 15:00 前，取上一日；否则取今日
    if today.hour < 15:
        today = today - timedelta(days=1)

    # 找最近的工作日
    while today.weekday() >= 5:  # 周六=5, 周日=6
        today = today - timedelta(days=1)
    return today.strftime("%Y%m%d")


if __name__ == "__main__":
    # 测试: 抓取单只股票
    df = fetch_single_stock("000001", start_date="20250101")
    print(df.head())
    print(f"\n{len(df)} 条记录")
