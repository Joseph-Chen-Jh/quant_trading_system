"""批量计算全市场筹码分布 (CYQ) 并入库

从 daily_price 表读取 301 只股票的 K线+换手率数据,
计算筹码分布衍生指标, upsert 到 chip_distribution 表.

运行方式:
    python experiments/backfill_chip_distribution.py

注意:
    - 计算速度约 0.1s/只, 全市场约 1 分钟
    - 可中断重跑 (已计算的不会重复, 基于 ts_code 检查)
    - 历史数据窗口: 2021-01-01 ~ 至今 (与 daily_price 对齐)
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from config import settings  # noqa: F401

import time
from datetime import datetime
from loguru import logger
from data.storage.database import DataStore
from data.storage.models import init_database
from data.processor.chip_distribution import ChipDistributionCalculator
from config.stock_pool_loader import load_pool

logger.add(
    "output/backfill_chip_distribution.log",
    level="INFO",
    rotation="10 MB",
    encoding="utf-8",
)

START_DATE = "20210101"


def backfill_all():
    """全市场批量计算筹码分布"""
    init_database()  # 确保 chip_distribution 表已建
    store = DataStore()
    calc = ChipDistributionCalculator()

    # 加载股票池
    pool_dict = load_pool("csi300")
    pool = [s["ts_code"] for s in pool_dict.get("stocks", [])]
    total = len(pool)
    logger.info(f"=== 开始计算筹码分布: {total} 只股票 ===")

    success = 0
    failed = []
    skipped = 0
    t_start = time.time()

    for i, ts_code in enumerate(pool):
        # 检查是否已计算 (基于已有记录数判断)
        existing = store.load_chip_distribution(ts_code=ts_code)
        if not existing.empty and len(existing) > 1000:
            skipped += 1
            continue

        try:
            # 读取 K线数据 (多拉 60 天预热, 保证第一天的筹码分布有历史支撑)
            df = store.load_daily_price(ts_code=ts_code, start=START_DATE)
            if df.empty:
                logger.warning(f"[{i+1}/{total}] {ts_code}: 无日线数据")
                failed.append(ts_code)
                continue

            # 检查 turnover 覆盖率
            if "turnover" not in df.columns or df["turnover"].notna().sum() < len(df) * 0.9:
                logger.warning(f"[{i+1}/{total}] {ts_code}: turnover 覆盖率不足")
                failed.append(ts_code)
                continue

            # 计算
            result = calc.compute(df)
            if result.empty:
                logger.warning(f"[{i+1}/{total}] {ts_code}: 计算结果为空")
                failed.append(ts_code)
                continue

            # 入库
            store.save_chip_distribution(result)
            success += 1
            logger.info(
                f"[{i+1}/{total}] {ts_code}: {len(result)} 行, "
                f"平均成本={result['avg_cost'].iloc[-1]:.2f}, "
                f"获利比例={result['profit_ratio'].iloc[-1]:.2%}"
            )

        except Exception as e:
            logger.error(f"[{i+1}/{total}] {ts_code} 失败: {e}")
            failed.append(ts_code)

    elapsed = time.time() - t_start
    logger.info(f"\n=== 计算完成 (耗时 {elapsed:.1f}s) ===")
    logger.info(f"总计: {total} 只")
    logger.info(f"成功: {success} 只")
    logger.info(f"失败: {len(failed)} 只: {failed}")
    logger.info(f"跳过 (已计算): {skipped} 只")


if __name__ == "__main__":
    backfill_all()
