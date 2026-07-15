"""
从 akshare 拉取沪深300成分股, 写入 stock_pool.yaml

用法:
    python data/fetcher/fetch_csi300_pool.py              # 默认取前100只写入 csi100
    python data/fetcher/fetch_csi300_pool.py --top 100    # 取前100只写入 csi100
    python data/fetcher/fetch_csi300_pool.py --all        # 全部300只写入 csi300

说明:
    - 沪深300成分股按市值排序, 前100只即最大的100只大盘股
    - weight 统一设为 0.20 (单股风险上限, 与池子规模解耦)
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import yaml
import akshare as ak
from loguru import logger


POOL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "stock_pool.yaml"
)


def code_to_ts_code(code: str, exchange: str) -> str:
    """成分券代码 + 交易所 → ts_code (如 000001.SZ)"""
    if "上海" in exchange:
        return f"{code}.SH"
    elif "深圳" in exchange:
        return f"{code}.SZ"
    # 兜底: 按代码前缀判断
    if code.startswith("6"):
        return f"{code}.SH"
    return f"{code}.SZ"


def fetch_csi300_stocks(top_n: int = None):
    """拉取沪深300成分股, 返回 stocks 列表"""
    logger.info(f"拉取沪深300成分股...")
    df = ak.index_stock_cons_csindex(symbol="000300")
    if df.empty:
        logger.error("拉取失败, 返回空数据")
        return []

    if top_n:
        df = df.head(top_n)
        pool_name = "csi100"
        pool_desc = f"从沪深300成分股中按市值取前{top_n}只"
    else:
        pool_name = "csi300"
        pool_desc = "沪深300全部成分股"

    stocks = []
    for _, row in df.iterrows():
        code = str(row["成分券代码"]).zfill(6)
        name = row["成分券名称"]
        exchange = row["交易所"]
        ts_code = code_to_ts_code(code, exchange)
        stocks.append({
            "ts_code": ts_code,
            "name": name,
            "weight": 0.20,
        })

    logger.info(f"成功获取 {len(stocks)} 只股票")
    logger.info(f"前5只: {[(s['ts_code'], s['name']) for s in stocks[:5]]}")
    return stocks, pool_name, pool_desc


def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--top", type=int, default=100, help="取前 N 只 (默认 100)")
    parser.add_argument("--all", action="store_true", help="拉取全部300只写入 csi300 池")
    args = parser.parse_args()

    top_n = None if args.all else args.top
    stocks, pool_name, pool_desc = fetch_csi300_stocks(top_n=top_n)
    if not stocks:
        return

    # 读取现有 YAML
    with open(POOL_FILE, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    # 覆盖/新增池子
    config["pools"][pool_name] = {
        "name": pool_desc,
        "description": f"{pool_desc}, 用于事前波动率筛选验证",
        "stocks": stocks,
    }

    # 写回 YAML
    with open(POOL_FILE, "w", encoding="utf-8") as f:
        yaml.dump(config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

    logger.info(f"已写入 {pool_name} 池子到 {POOL_FILE}")
    logger.info(f"池子规模: {len(stocks)} 只, weight=0.20")


if __name__ == "__main__":
    main()
