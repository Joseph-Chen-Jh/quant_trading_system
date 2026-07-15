"""数据相关命令: 更新数据、拉取股票池"""
import time
from loguru import logger


def cmd_update_data():
    """增量更新数据"""
    from data.fetcher.pipeline import pipeline_update
    pipeline_update()


def _ensure_pool_data(store, pool: dict, start_date: str, end_date: str = None):
    """确保池中所有股票的日线数据已存在于数据库, 缺失则自动拉取"""
    from data.fetcher.stock_daily import fetch_single_stock_by_ts_code
    from data.cleaner.cleaner import clean_daily_price

    total = len(pool["stocks"])
    missing = []
    for stock in pool["stocks"]:
        ts_code = stock["ts_code"]
        df = store.load_daily_price(ts_code=ts_code, start=start_date, end=end_date)
        if df.empty:
            missing.append(stock)

    if not missing:
        logger.info(f"所有 {total} 只股票数据已就绪")
        return

    logger.info(f"{len(missing)}/{total} 只股票数据缺失, 开始拉取...")
    for i, stock in enumerate(missing, 1):
        ts_code = stock["ts_code"]
        name = stock.get("name", ts_code)
        logger.info(f"[{i}/{len(missing)}] 拉取 {name} ({ts_code}) ...")
        try:
            raw = fetch_single_stock_by_ts_code(ts_code, start_date=start_date)
            if raw is not None and not raw.empty:
                raw = clean_daily_price(raw)
                store.save_daily_price(raw)
            else:
                logger.warning(f"[{i}/{len(missing)}] {ts_code} 拉取失败")
        except Exception as e:
            logger.error(f"[{i}/{len(missing)}] {ts_code} 拉取异常: {e}")
        time.sleep(0.5)


def cmd_fetch_pool(pool_name: str = "default", start_date: str = "20240101"):
    """拉取股票池中所有股票的日线数据"""
    from config.stock_pool_loader import load_pool
    from data.storage.database import DataStore
    from data.fetcher.stock_daily import fetch_single_stock_by_ts_code
    from data.cleaner.cleaner import clean_daily_price

    pool = load_pool(pool_name)
    store = DataStore()
    total = len(pool["stocks"])

    logger.info(f"=== 拉取股票池 [{pool_name}] 数据 ({total} 只) ===")
    success = 0
    for i, stock in enumerate(pool["stocks"], 1):
        ts_code = stock["ts_code"]
        name = stock.get("name", ts_code)
        logger.info(f"[{i}/{total}] {name} ({ts_code}) ...")

        try:
            df = fetch_single_stock_by_ts_code(ts_code, start_date=start_date)
            if df is None or df.empty:
                logger.warning(f"  {ts_code} 返回空数据")
                continue
            df = clean_daily_price(df)
            store.save_daily_price(df)
            success += 1
            time.sleep(0.5)  # 避免 akshare 频率限制
        except Exception as e:
            logger.error(f"  {ts_code} 拉取失败: {e}")

    logger.info(f"=== 拉取完成: {success}/{total} 只成功 ===")
