"""
动态波动率筛选器

职责:
    每月调仓日, 从候选池中按"过去 N 天日收益率标准差"排序,
    选出波动率最高的 top_n 只股票作为"可买入池"。

设计要点 (方式 B):
    - 只更新"可买入池", 不清仓已持仓
    - 已持仓的股票即使跌出 top_n, 也继续持有, 交给 MA 死叉/止损决定何时卖
    - 新买入信号只允许买"可买入池"里的股票
"""
import pandas as pd
import numpy as np
from typing import List, Dict
from loguru import logger


class VolatilitySelector:
    """动态波动率筛选器"""

    def __init__(
        self,
        lookback_days: int = 60,
        top_n: int = 10,
        rebalance_freq: str = "monthly",
    ):
        """
        Args:
            lookback_days: 计算波动率的回看天数 (交易日)
            top_n:         选波动率前 N 只
            rebalance_freq: 调仓频率 ("monthly" 每月 / "weekly" 每周)
        """
        self.lookback_days = lookback_days
        self.top_n = top_n
        self.rebalance_freq = rebalance_freq

        # 当前可买入池
        self.tradable_pool: List[str] = []
        # 调仓历史 (用于日志和分析)
        self.rebalance_history: List[dict] = []

    def is_rebalance_day(self, date: str, prev_date: str = None) -> bool:
        """
        判断是否为调仓日

        monthly: 每月第一个交易日 (月份变化)
        weekly:  每周一 (星期一 = 0)
        """
        if prev_date is None:
            return True  # 回测第一天调仓

        if self.rebalance_freq == "monthly":
            # 月份变化即调仓
            return date[:6] != prev_date[:6]
        elif self.rebalance_freq == "weekly":
            d = pd.to_datetime(date)
            return d.weekday() == 0  # 周一
        return False

    def compute_volatility(
        self,
        ts_code: str,
        stock_data: pd.DataFrame,
        current_date: str,
    ) -> float:
        """
        计算某只股票到 current_date 为止的过去 lookback_days 天的日收益率标准差

        Args:
            ts_code:      股票代码
            stock_data:   该股票的完整日线数据
            current_date: 当前日期 YYYYMMDD

        Returns:
            年化波动率 (float), 如果数据不足返回 0
        """
        df = stock_data[stock_data["trade_date"] <= current_date].tail(self.lookback_days)
        if len(df) < 20:  # 至少 20 天数据才计算
            return 0.0

        daily_ret = df["close"].pct_change().dropna()
        if len(daily_ret) < 10:
            return 0.0

        # 年化波动率 = 日波动率 × sqrt(244)
        return daily_ret.std() * np.sqrt(244)

    def update_pool(
        self,
        all_codes: List[str],
        stock_data: Dict[str, pd.DataFrame],
        current_date: str,
    ) -> List[str]:
        """
        更新可买入池: 按波动率排序选 top_n

        Args:
            all_codes:    候选池所有股票代码
            stock_data:   {ts_code: DataFrame}
            current_date: 当前日期

        Returns:
            新的可买入池 (ts_code 列表)
        """
        volatilities = []
        for ts_code in all_codes:
            if ts_code not in stock_data:
                continue
            vol = self.compute_volatility(ts_code, stock_data[ts_code], current_date)
            if vol > 0:
                volatilities.append((ts_code, vol))

        # 按波动率降序排序, 取前 top_n
        volatilities.sort(key=lambda x: x[1], reverse=True)
        new_pool = [code for code, _ in volatilities[:self.top_n]]

        self.tradable_pool = new_pool
        self.rebalance_history.append({
            "date": current_date,
            "pool": new_pool.copy(),
            "volatilities": dict(volatilities[:self.top_n]),
        })

        if new_pool:
            min_vol = volatilities[len(new_pool)-1][1] if len(volatilities) >= len(new_pool) else 0
            logger.info(
                f"波动率调仓 {current_date}: 选出 {len(new_pool)} 只, "
                f"最低波动率 {min_vol:.1%}"
            )

        return new_pool

    def can_buy(self, ts_code: str) -> bool:
        """判断某只股票当前是否允许买入"""
        if not self.tradable_pool:
            return True  # 未初始化时全部允许
        return ts_code in self.tradable_pool
