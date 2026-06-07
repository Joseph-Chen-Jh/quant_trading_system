"""
数据管线 — 一键抓取、清洗、存储

用法:
    # 首次全量抓取 (5年日线)
    python data/fetcher/pipeline.py --mode full --years 5

    # 每日增量更新
    python data/fetcher/pipeline.py --mode update

    # 只更新股票列表
    python data/fetcher/pipeline.py --mode stocks
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import argparse
import time
from datetime import datetime, timedelta
from loguru import logger

# 本地导入
from data.fetcher.stock_basic import fetch_all_stocks, get_stock_pool
from data.fetcher.stock_daily import fetch_batch, fetch_daily_increment
from data.fetcher.index import fetch_all_indices
from data.fetcher.financial import get_latest_financial_snapshot
from data.cleaner.cleaner import clean_daily_price, clean_stock_basic
from data.cleaner.validator import validate_daily_price
from data.storage.database import DataStore
from config.settings import AKSHARE_REQUEST_INTERVAL


def pipeline_full(years: int = 5):
    """
    全量数据抓取管线
    1. 股票列表 → 2. 指数日线 → 3. 全市场日线 → 4. 财务快照
    """
    store = DataStore()
    start_date = (datetime.now() - timedelta(days=years * 365)).strftime("%Y%m%d")
    end_date = datetime.now().strftime("%Y%m%d")

    # ----- 1. 股票列表 -----
    logger.info("=" * 40)
    logger.info("Step 1/4: 抓取股票列表")
    stocks = fetch_all_stocks()
    stocks = clean_stock_basic(stocks)
    store.save_stock_basic(stocks)

    # 生成股票池（排除 ST）
    pool = get_stock_pool(stocks, exclude_st=True)
    codes = pool["ts_code"].tolist()
    logger.info(f"可交易股票池: {len(codes)} 只")

    # ----- 2. 指数日线 -----
    logger.info("=" * 40)
    logger.info("Step 2/4: 抓取指数日线")
    index_df = fetch_all_indices(start_date="20150101", end_date=end_date)
    if not index_df.empty:
        index_df = clean_daily_price(index_df.rename(
            columns={c: c for c in index_df.columns if c in ["ts_code", "trade_date", "open", "high", "low", "close", "volume", "amount"]}
        ))
        store.save_index_daily(index_df)
    logger.info(f"指数数据: {len(index_df)} 行")

    # ----- 3. 全市场日线（耗时最长） -----
    logger.info("=" * 40)
    logger.info(f"Step 3/4: 抓取全市场日线 ({start_date} ~ {end_date})")
    logger.warning(f"预计耗时: 约 {len(codes) * AKSHARE_REQUEST_INTERVAL / 60:.0f} 分钟 (请耐心等待)")

    # 分批抓取 + 分批存储，避免内存爆 + 中断丢失
    batch_size = 200
    for i in range(0, len(codes), batch_size):
        batch = codes[i:i + batch_size]
        logger.info(f"批次 {i // batch_size + 1}: {batch[0]} ~ {batch[-1]} ({len(batch)} 只)")

        df = fetch_batch(batch, start_date=start_date, end_date=end_date)
        if not df.empty:
            df = clean_daily_price(df)
            store.save_daily_price(df, replace=False)

    logger.info("全市场日线抓取完成")

    # ----- 4. 财务快照 -----
    logger.info("=" * 40)
    logger.info("Step 4/4: 抓取财务快照 (只取前200只大市值作示例，全量很慢)")
    sample = pool.head(200)
    fin_df = get_latest_financial_snapshot(sample)
    if not fin_df.empty:
        store.save_financial_snapshot(fin_df)

    logger.info("=" * 40)
    logger.info("全量数据管线执行完毕!")


def pipeline_update():
    """每日增量更新管线"""
    store = DataStore()

    # 1. 加载现有股票池
    stocks = store.load_stock_basic()
    if stocks.empty:
        logger.warning("数据库无股票列表，请先运行 --mode stocks 或 --mode full")
        return

    pool = get_stock_pool(stocks)
    codes = pool["ts_code"].tolist()

    # 2. 增量抓取最近一天日线
    logger.info(f"增量更新 {len(codes)} 只股票...")
    df = fetch_daily_increment(codes)
    if not df.empty:
        df = clean_daily_price(df)
        store.save_daily_price(df, replace=False)

    # 3. 更新指数
    logger.info("更新指数数据...")
    index_df = fetch_all_indices(
        start_date=(datetime.now() - timedelta(days=7)).strftime("%Y%m%d")
    )
    if not index_df.empty:
        store.save_index_daily(index_df)

    logger.info("增量更新完成")


def pipeline_stocks_only():
    """仅更新股票列表"""
    store = DataStore()
    stocks = fetch_all_stocks()
    stocks = clean_stock_basic(stocks)
    store.save_stock_basic(stocks)
    logger.info(f"股票列表已更新: {len(stocks)} 只")


def main():
    parser = argparse.ArgumentParser(description="数据管线")
    parser.add_argument("--mode", choices=["full", "update", "stocks"],
                        default="stocks", help="运行模式")
    parser.add_argument("--years", type=int, default=5, help="回溯年数 (full模式)")
    parser.add_argument("--limit", type=int, default=0,
                        help="限制股票数 (0=全部, 方便测试)")
    args = parser.parse_args()

    if args.mode == "full":
        pipeline_full(years=args.years)
    elif args.mode == "update":
        pipeline_update()
    elif args.mode == "stocks":
        pipeline_stocks_only()


if __name__ == "__main__":
    main()
