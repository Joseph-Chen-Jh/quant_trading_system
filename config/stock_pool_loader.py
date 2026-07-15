"""
股票池加载器 — 从 YAML 读取股票池定义
"""
import os
from typing import Dict, List
from loguru import logger
import yaml

# 默认股票池文件路径
POOL_FILE = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "config", "stock_pool.yaml"
)


def load_pool(pool_name: str = "default", file_path: str = None) -> Dict:
    """
    加载指定名称的股票池

    Args:
        pool_name: 池名称 (对应 YAML 中 pools 下的 key)
        file_path: YAML 文件路径 (默认用 config/stock_pool.yaml)

    Returns:
        {
            "name": "默认高波动池",
            "description": "...",
            "stocks": [
                {"ts_code": "300750.SZ", "name": "宁德时代", "weight": 0.25},
                ...
            ]
        }

    Raises:
        FileNotFoundError: YAML 文件不存在
        KeyError: pool_name 在 YAML 中不存在
    """
    path = file_path or POOL_FILE
    if not os.path.exists(path):
        raise FileNotFoundError(f"股票池配置文件不存在: {path}")

    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    pools = config.get("pools", {})
    if pool_name not in pools:
        available = list(pools.keys())
        raise KeyError(f"股票池 '{pool_name}' 不存在, 可用池: {available}")

    pool = pools[pool_name]
    logger.info(
        f"加载股票池 [{pool_name}]: {pool.get('name', '')} "
        f"({len(pool.get('stocks', []))} 只股票)"
    )
    return pool


def list_pools(file_path: str = None) -> List[str]:
    """列出所有可用股票池名称"""
    path = file_path or POOL_FILE
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    return list(config.get("pools", {}).keys())


if __name__ == "__main__":
    # 自测: 列出并加载所有池
    import sys
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from config.log_config import logger  # noqa

    print(f"可用股票池: {list_pools()}")
    for name in list_pools():
        pool = load_pool(name)
        print(f"\n[{name}] {pool['name']}")
        print(f"  描述: {pool.get('description', '')}")
        for s in pool["stocks"]:
            print(f"  - {s['ts_code']} {s['name']} (权重 {s['weight']:.0%})")
