"""
交易日历工具
"""
import pandas as pd
from datetime import datetime, timedelta


class TradeCalendar:
    """A股交易日历 (基于 pandas 工作日)"""

    @staticmethod
    def is_trade_day(date_str: str) -> bool:
        """判断是否为交易日 (简易版: 周一到周五)"""
        dt = pd.Timestamp(date_str)
        return dt.dayofweek < 5  # 周一=0, 周五=4

    @staticmethod
    def get_trade_days(start: str, end: str) -> list:
        """获取区间内所有交易日"""
        days = pd.bdate_range(start=start, end=end)
        return [d.strftime("%Y%m%d") for d in days]

    @staticmethod
    def next_trade_day(date_str: str, offset: int = 1) -> str:
        """获取下/上 N 个交易日"""
        dt = pd.Timestamp(date_str)
        freq = f"{offset}B" if offset > 0 else f"{-offset}B"
        ds = pd.bdate_range(start=dt, periods=abs(offset) + 1, freq="B")
        if offset > 0:
            return ds[-1].strftime("%Y%m%d")
        else:
            return ds[0].strftime("%Y%m%d")

    @staticmethod
    def today_str() -> str:
        return datetime.now().strftime("%Y%m%d")


# 模块级单例
trade_calendar = TradeCalendar()
