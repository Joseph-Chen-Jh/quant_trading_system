"""
策略基类
"""
from abc import ABC, abstractmethod
from typing import Dict, List
import pandas as pd


class BaseStrategy(ABC):
    """所有策略的抽象基类"""

    def __init__(self, name: str = "BaseStrategy"):
        self.name = name
        self.params = {}

    @abstractmethod
    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        生成交易信号

        Args:
            data: 必须包含 ts_code, trade_date, open, high, low, close, volume
        Returns:
            DataFrame with columns: ts_code, trade_date, action (BUY/SELL/HOLD)
        """
        pass

    def recommend(self, data: pd.DataFrame, top_n: int = 10, **kwargs) -> List[Dict]:
        """
        推荐股票列表 (用于选股策略)

        Returns:
            [{ts_code, score, reason}, ...]
        """
        return []
