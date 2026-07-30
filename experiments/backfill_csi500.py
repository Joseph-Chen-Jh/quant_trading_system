"""回填中证500新增股票的日线+换手率+筹码分布

只回填 csi500 中不在 csi300 的股票 (避免重复拉取已有的300只).
日线用新浪源 (自带 turnover), 筹码分布用自计算模块.

运行方式:
    python experiments/backfill_csi500.py

注意:
    - 约 500 只新股 × 5年, 预计 15-30 分钟
    - 可中断重跑 (已回填的会跳过)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings  # noqa: F401

import time
from datetime import datetime
from loguru import logger
from data.storage.database import DataStore
from data.storage.models import init_database
from data.fetcher.stock_daily import fetch_single_stock_by_ts_code
from data.cleaner.cleaner import clean_daily_price
from data.processor.chip_distribution import ChipDistributionCalculator
from config.stock_pool_loader import load_pool

logger.add(
    "output/backfill_csi500.log",
    level="INFO",
    rotation="10 MB",
    encoding="utf-8",
)

START_DATE = "20210101"


def main():
    init_database()
    store = DataStore()
    calc = ChipDistributionCalculator()

    # 加载两个池, 找出 csi500 中不在 csi300 的新股票
    csi300_codes = {s["ts_code"] for s in load_pool("csi300").get("stocks", [])}
    csi500_dict = load_pool("csi500")
    csi500_stocks = csi500_dict.get("stocks", [])
    new_stocks = [s for s in csi500_stocks if s["ts_code"] not in csi300_codes]

    total = len(new_stocks)
    logger.info(f"=== 中证500回填: {total} 只新股 (csi500共{len(csi500_stocks)}只, csi300已有{len(csi300_codes)}只) ===")

    success_daily = 0
    success_chip = 0
    failed = []
    skipped = 0
    t_start = time.time()

    for i, stock in enumerate(new_stocks):
        ts_code = stock["ts_code"]
        name = stock.get("name", ts_code)

        # 检查日线是否已回填 (turnover 非空率 > 90%)
        existing = store.load_daily_price(ts_code=ts_code, start=START_DATE)
        need_daily = True
        if not existing.empty and "turnover" in existing.columns:
            non_null_ratio = existing["turnover"].notna().sum() / len(existing)
            if non_null_ratio > 0.9:
                need_daily = False

        # 1. 回填日线
        if need_daily:
            try:
                df = fetch_single_stock_by_ts_code(
                    ts_code, start_date=START_DATE, end_date=datetime.now().strftime("%Y%m%d")
                )
                if df.empty:
                    logger.warning(f"[{i+1}/{total}] {ts_code} {name}: 返回空数据")
                    failed.append(ts_code)
                    time.sleep(0.3)
                    continue
                cleaned = clean_daily_price(df)
                store.save_daily_price(cleaned, replace=False)
                success_daily += 1
                nn = cleaned["turnover"].notna().sum() if "turnover" in cleaned.columns else 0
                logger.info(f"[{i+1}/{total}] {ts_code} {name}: {len(cleaned)}行, turnover非空{nn}")
            except Exception as e:
                logger.error(f"[{i+1}/{total}] {ts_code} {name}: 日线失败: {e}")
                failed.append(ts_code)
                time.sleep(0.3)
                continue
            time.sleep(0.3)
        else:
            skipped += 1

        # 2. 回填筹码分布
        try:
            existing_chip = store.load_chip_distribution(ts_code=ts_code)
            if not existing_chip.empty and len(existing_chip) > 1000:
                continue
            df = store.load_daily_price(ts_code=ts_code, start=START_DATE)
            if df.empty:
                continue
            if "turnover" not in df.columns or df["turnover"].notna().sum() < len(df) * 0.9:
                logger.warning(f"[{i+1}/{total}] {ts_code}: turnover覆盖率不足, 跳过筹码")
                continue
            result = calc.compute(df)
            if result.empty:
                continue
            store.save_chip_distribution(result)
            success_chip += 1
        except Exception as e:
            logger.error(f"[{i+1}/{total}] {ts_code}: 筹码失败: {e}")

        if (i + 1) % 50 == 0:
            elapsed = time.time() - t_start
            logger.info(f"--- 进度: {i+1}/{total} (日线{success_daily}, 筹码{success_chip}, 跳过{skipped}, 失败{len(failed)}, 耗时{elapsed:.0f}s) ---")

    elapsed = time.time() - t_start
    logger.info(f"\n=== 回填完成 (耗时 {elapsed:.1f}s) ===")
    logger.info(f"总计: {total} 只新股")
    logger.info(f"日线成功: {success_daily} 只")
    logger.info(f"筹码成功: {success_chip} 只")
    logger.info(f"跳过(已有): {skipped} 只")
    logger.info(f"失败: {len(failed)} 只: {failed}")


if __name__ == "__main__":
    main()
