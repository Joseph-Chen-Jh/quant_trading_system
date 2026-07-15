"""
PE 历史分位数选股策略

逻辑:
    在每个调仓日, 对每只候选股票计算当前 PE 在过去 N 年历史中的分位数,
    选出分位数最低的 top_n 只股票 (估值相对自身历史最便宜).

    - 分位数 = 当前 PE 在历史 PE 序列中的百分位 (0% = 历史最低, 100% = 历史最高)
    - 选分位数 < threshold 的股票, 按分位数升序取前 top_n 只
    - 等权持有, 定期调仓

适用场景:
    - 价值投资: 买入"相对便宜"的股票
    - 横截面选股: 和 MA 择时 (时间序列) 互补

参数:
    - quantile_threshold: PE 分位数上限, 默认 0.3 (只选历史 30% 分位以下的)
    - lookback_years: 计算分位数的历史窗口, 默认 3 年
    - top_n: 最多持有的股票数, 默认 5
    - rebalance_freq: 调仓频率, 'monthly' / 'quarterly'
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from datetime import datetime, timedelta
from loguru import logger

from strategy.base_strategy import BaseStrategy


class PEQuantileStrategy(BaseStrategy):
    """PE 历史分位数选股策略"""

    def __init__(
        self,
        quantile_threshold: float = 0.3,
        lookback_years: int = 3,
        top_n: int = 5,
        rebalance_freq: str = "monthly",
    ):
        super().__init__(name="PE_Quantile")
        self.quantile_threshold = quantile_threshold
        self.lookback_years = lookback_years
        self.top_n = top_n
        self.rebalance_freq = rebalance_freq
        self.params = {
            "quantile_threshold": quantile_threshold,
            "lookback_years": lookback_years,
            "top_n": top_n,
            "rebalance_freq": rebalance_freq,
        }

    def generate_signals(self, data: pd.DataFrame, **kwargs) -> pd.DataFrame:
        """
        选股策略不用 generate_signals (那是择时策略的接口).
        这里保留兼容, 实际选股逻辑在 recommend() 里.
        """
        return pd.DataFrame()

    def recommend(
        self,
        pe_data: Dict[str, pd.DataFrame],
        current_date: str,
        **kwargs,
    ) -> List[Dict]:
        """
        在调仓日选出 PE 分位数最低的股票

        Args:
            pe_data: {ts_code: DataFrame[trade_date, pe]}
                     每只股票的历史 PE 序列
            current_date: 调仓日 YYYYMMDD
        Returns:
            [{ts_code, score, reason, current_pe, pe_quantile}, ...]
            score = 1 - pe_quantile (分位数越低, 分数越高)
        """
        scores = []
        lookback_start = self._lookback_start_date(current_date)

        for ts_code, df in pe_data.items():
            if df.empty or "pe" not in df.columns or "trade_date" not in df.columns:
                continue

            df = df.copy()
            df["trade_date"] = df["trade_date"].astype(str)

            # 取历史窗口内的数据
            hist = df[(df["trade_date"] >= lookback_start) &
                      (df["trade_date"] <= current_date)].copy()

            if len(hist) < 60:  # 至少 60 个交易日才有统计意义
                continue

            # 获取当前 PE (调仓日或之前最近的 PE)
            current_row = hist[hist["trade_date"] <= current_date]
            if current_row.empty:
                continue
            current_pe = current_row.iloc[-1]["pe"]

            if pd.isna(current_pe) or current_pe <= 0:
                continue  # 亏损股票 PE 为负或 NaN, 跳过

            # 计算分位数: 当前 PE 在历史 PE 序列中的百分位
            hist_pe = hist["pe"].dropna()
            hist_pe = hist_pe[hist_pe > 0]  # 排除负 PE

            if len(hist_pe) < 60:
                continue

            pe_quantile = (hist_pe <= current_pe).sum() / len(hist_pe)

            scores.append({
                "ts_code": ts_code,
                "current_pe": round(current_pe, 2),
                "pe_quantile": round(pe_quantile, 4),
                "score": round(1 - pe_quantile, 4),
                "reason": f"PE={current_pe:.1f}, 分位数={pe_quantile:.0%}",
            })

        # 筛选: 分位数 < threshold
        qualified = [s for s in scores if s["pe_quantile"] < self.quantile_threshold]

        # 按分位数升序 (越低越便宜), 取 top_n
        qualified.sort(key=lambda x: x["pe_quantile"])
        selected = qualified[:self.top_n]

        logger.info(
            f"PE 选股 {current_date}: 候选 {len(scores)} 只, "
            f"分位数 < {self.quantile_threshold:.0%} 的 {len(qualified)} 只, "
            f"选出 {len(selected)} 只"
        )

        return selected

    def get_rebalance_dates(self, all_dates: List[str]) -> List[str]:
        """
        根据调仓频率, 从所有交易日中选出调仓日

        Args:
            all_dates: 所有交易日列表 YYYYMMDD
        Returns:
            调仓日列表 (每月/每季第一个交易日)
        """
        dates = sorted(all_dates)
        rebalance_dates = []
        last_key = None

        for date_str in dates:
            dt = datetime.strptime(date_str, "%Y%m%d")
            if self.rebalance_freq == "monthly":
                key = (dt.year, dt.month)
            elif self.rebalance_freq == "quarterly":
                key = (dt.year, (dt.month - 1) // 3 + 1)
            else:
                raise ValueError(f"未知调仓频率: {self.rebalance_freq}")

            if key != last_key:
                rebalance_dates.append(date_str)
                last_key = key

        return rebalance_dates

    def _lookback_start_date(self, current_date: str) -> str:
        """计算历史窗口起始日期"""
        dt = datetime.strptime(current_date, "%Y%m%d")
        start = dt - timedelta(days=self.lookback_years * 365)
        return start.strftime("%Y%m%d")


if __name__ == "__main__":
    # 自测: 用模拟 PE 数据验证选股逻辑
    print("=" * 60)
    print("PE 分位数选股策略 自测")
    print("=" * 60)

    np.random.seed(42)

    # 构造 5 只股票的模拟 PE 数据 (3 年)
    dates = pd.bdate_range("2021-01-01", "2024-01-01")
    date_strs = [d.strftime("%Y%m%d") for d in dates]

    pe_data = {}
    for i, code in enumerate(["000001.SZ", "000002.SZ", "600519.SH", "300750.SZ", "002594.SZ"]):
        # 每只股票有不同的 PE 基准和波动
        base_pe = 10 + i * 5
        pe_series = base_pe + np.random.randn(len(dates)) * 2 + np.sin(np.arange(len(dates)) * 0.01) * 3
        pe_series = np.maximum(pe_series, 3)  # PE > 0
        pe_data[code] = pd.DataFrame({
            "ts_code": code,
            "trade_date": date_strs,
            "pe": pe_series,
        })

    strategy = PEQuantileStrategy(
        quantile_threshold=0.3,
        lookback_years=3,
        top_n=3,
        rebalance_freq="monthly",
    )

    # 测试1: 选股
    print("\n--- 测试1: 单次选股 ---")
    selected = strategy.recommend(pe_data, "20240101")
    print(f"选出 {len(selected)} 只 (应 <= 3):")
    for s in selected:
        print(f"  {s['ts_code']}: PE={s['current_pe']}, 分位数={s['pe_quantile']:.0%}, "
              f"分数={s['score']:.2f}, {s['reason']}")

    # 测试2: 调仓日
    print("\n--- 测试2: 月度调仓日 ---")
    rebalance_dates = strategy.get_rebalance_dates(date_strs[:60])
    print(f"60 个交易日中有 {len(rebalance_dates)} 个调仓日")
    print(f"前 3 个: {rebalance_dates[:3]}")
    assert len(rebalance_dates) >= 2, "应至少有 2 个调仓日 (跨月)"

    # 测试3: 分位数阈值过滤
    print("\n--- 测试3: 分位数阈值过滤 ---")
    strategy_strict = PEQuantileStrategy(quantile_threshold=0.1, top_n=5)
    selected_strict = strategy_strict.recommend(pe_data, "20240101")
    print(f"threshold=0.1: 选出 {len(selected_strict)} 只 (应少于 threshold=0.3 的)")
    for s in selected_strict:
        print(f"  {s['ts_code']}: 分位数={s['pe_quantile']:.0%}")
        assert s["pe_quantile"] < 0.1, "所有选出的分位数应 < 0.1"

    print("\n✓ 全部测试通过")
