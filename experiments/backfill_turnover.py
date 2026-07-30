"""全量回填换手率 (turnover)

从 akshare 新浪源重新拉取所有股票 5 年日线数据 (自带 turnover 字段),
清洗后 upsert 到 daily_price 表 (INSERT OR REPLACE, 主键冲突整行替换, 不丢数据).

运行方式:
    python experiments/backfill_turnover.py

注意:
    - 一次性操作, 约 30-60 分钟 (301 只股票 × 5年)
    - 新浪源失败时会自动用 TickFlow 补齐其他字段 (turnover 仍为 NULL)
    - 进度每 50 只打印一次, 可中断重跑 (已回填的不会重复拉取)
    - 代理处理由 config.settings 统一负责 (monkey-patch requests.utils.get_environ_proxies)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 导入 settings 触发代理 monkey-patch (必须在导入 fetcher 之前)
from config import settings  # noqa: F401

import time
from datetime import datetime
from loguru import logger
from data.storage.database import DataStore
from data.fetcher.stock_daily import fetch_single_stock_by_ts_code
from data.cleaner.cleaner import clean_daily_price
from config.stock_pool_loader import load_pool

# 配置日志到文件
logger.add(
    "output/backfill_turnover.log",
    level="INFO",
    rotation="10 MB",
    encoding="utf-8",
)


def backfill_all(start_date: str = "20210101", end_date: str = None):
    """全量回填换手率"""
    if end_date is None:
        end_date = datetime.now().strftime("%Y%m%d")

    store = DataStore()

    # 加载 csi300 股票池 (load_pool 返回字典, stocks 是字典列表)
    pool_dict = load_pool("csi300")
    pool = [s["ts_code"] for s in pool_dict.get("stocks", [])]
    total = len(pool)
    logger.info(f"=== 开始回填换手率: {total} 只股票, {start_date} ~ {end_date} ===")

    success = 0
    failed = []
    skipped = 0

    for i, ts_code in enumerate(pool):
        # 检查是否已回填 (turnover 非 NULL 的比例 > 90% 视为已回填)
        # 这样中断后重跑不会重复拉取
        existing = store.load_daily_price(ts_code=ts_code, start=start_date)
        if not existing.empty and "turnover" in existing.columns:
            non_null_ratio = existing["turnover"].notna().sum() / len(existing)
            if non_null_ratio > 0.9:
                skipped += 1
                continue

        try:
            df = fetch_single_stock_by_ts_code(
                ts_code, start_date=start_date, end_date=end_date
            )
            if df.empty:
                logger.warning(f"[{i+1}/{total}] {ts_code} 返回空数据")
                failed.append(ts_code)
                continue

            # 清洗 + 存储 (upsert, 不丢数据)
            cleaned = clean_daily_price(df)
            store.save_daily_price(cleaned, replace=False)

            # 统计 turnover 非空率
            if "turnover" in cleaned.columns:
                nn = cleaned["turnover"].notna().sum()
                total_n = len(cleaned)
                logger.info(
                    f"[{i+1}/{total}] {ts_code}: {total_n} 行, "
                    f"turnover 非空 {nn}/{total_n} ({100*nn/max(total_n,1):.0f}%)"
                )
                if nn > 0:
                    success += 1
                else:
                    failed.append(ts_code)
            else:
                logger.warning(f"[{i+1}/{total}] {ts_code}: 无 turnover 列")
                failed.append(ts_code)

        except Exception as e:
            logger.error(f"[{i+1}/{total}] {ts_code} 失败: {e}")
            failed.append(ts_code)

        # 请求间隔 (避免 akshare 限流)
        time.sleep(0.3)

        # 每 50 只打印进度
        if (i + 1) % 50 == 0:
            logger.info(
                f"--- 进度: {i+1}/{total} "
                f"(成功 {success}, 失败 {len(failed)}, 跳过 {skipped}) ---"
            )

    logger.info(f"\n=== 回填完成 ===")
    logger.info(f"总计: {total} 只")
    logger.info(f"成功: {success} 只")
    logger.info(f"失败: {len(failed)} 只: {failed}")
    logger.info(f"跳过 (已回填): {skipped} 只")


if __name__ == "__main__":
    backfill_all(start_date="20210101")
