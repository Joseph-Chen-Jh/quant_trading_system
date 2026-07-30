"""从 akshare 拉取中证500成分股, 写入 stock_pool.yaml

用法:
    python data/fetcher/fetch_csi500_pool.py

说明:
    - 中证500成分股 (000905), 与沪深300不重叠的中盘股
    - weight 统一设为 0.20 (单股风险上限)
    - 会在 yaml 中新增 csi500 池子
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

# 导入 settings 触发代理 monkey-patch (必须在导入 akshare 之前)
from config import settings  # noqa: F401

import yaml
import akshare as ak
from loguru import logger


POOL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "config", "stock_pool.yaml"
)


def code_to_ts_code(code: str, exchange: str) -> str:
    """成分券代码 + 交易所 → ts_code"""
    if "上海" in exchange:
        return f"{code}.SH"
    elif "深圳" in exchange:
        return f"{code}.SZ"
    if code.startswith("6"):
        return f"{code}.SH"
    return f"{code}.SZ"


def fetch_csi500_stocks():
    """拉取中证500成分股, 返回 stocks 列表

    使用 ak.index_stock_cons (东方财富源), 比 csindex 源快
    返回列: 品种代码, 品种名称, 纳入日期
    """
    logger.info("拉取中证500成分股...")
    df = ak.index_stock_cons(symbol="000905")
    if df.empty:
        logger.error("拉取失败, 返回空数据")
        return []

    stocks = []
    for _, row in df.iterrows():
        code = str(row["品种代码"]).zfill(6)
        name = row["品种名称"]
        # index_stock_cons 不返回交易所, 按代码前缀判断
        if code.startswith("6") or code.startswith("9"):
            ts_code = f"{code}.SH"
        else:
            ts_code = f"{code}.SZ"
        stocks.append({
            "ts_code": ts_code,
            "name": name,
            "weight": 0.20,
        })

    logger.info(f"成功获取 {len(stocks)} 只中证500成分股")
    logger.info(f"前5只: {[(s['ts_code'], s['name']) for s in stocks[:5]]}")
    return stocks


def main():
    stocks = fetch_csi500_stocks()
    if not stocks:
        return

    with open(POOL_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    config["pools"]["csi500"] = {
        "name": "中证500成分股",
        "description": "中证500全部成分股(中盘股), 与沪深300不重叠",
        "stocks": stocks,
    }

    with open(POOL_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info(f"已写入 csi500 池子到 {POOL_FILE}")
    logger.info(f"池子规模: {len(stocks)} 只, weight=0.20")


if __name__ == "__main__":
    main()
