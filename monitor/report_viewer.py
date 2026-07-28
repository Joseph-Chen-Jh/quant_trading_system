"""
回测结果分析模块

读取已生成的 backtest_nav.csv 和 backtest_trades.csv,
计算各项绩效指标, 供 dashboard.py 展示.

纯数据层, 不涉及 UI.
"""
import os
import sys
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd
import numpy as np

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# 年化因子: A 股一年约 244 交易日
ANN_FACTOR = 244


@dataclass
class BacktestReport:
    """回测报告数据容器"""
    nav: pd.DataFrame                     # 净值表
    trades: pd.DataFrame                  # 交易明细
    _metrics: dict = field(default_factory=dict, repr=False)

    def compute_metrics(self) -> dict:
        """计算所有绩效指标, 返回扁平字典"""
        if self._metrics:
            return self._metrics

        m = {}
        nav = self.nav
        trades = self.trades

        # 列名兼容
        asset_col = "nav" if "nav" in nav.columns else "total_asset"

        # --- 策略收益指标 ---
        if not nav.empty:
            initial = nav[asset_col].iloc[0]
            final = nav[asset_col].iloc[-1]
            m["initial_asset"] = initial
            m["final_asset"] = final
            m["total_return"] = final / initial - 1 if initial > 0 else 0
            m["n_days"] = len(nav)
            m["ann_return"] = (1 + m["total_return"]) ** (ANN_FACTOR / m["n_days"]) - 1

            # 最大回撤
            peak = nav[asset_col].cummax()
            dd = (nav[asset_col] - peak) / peak
            m["max_drawdown"] = dd.min()
            if "date" in nav.columns:
                m["max_dd_date"] = nav.iloc[dd.values.argmin()]["date"]
            else:
                m["max_dd_date"] = None

            # 波动率与夏普
            if "return" in nav.columns:
                daily_ret = nav["return"]
                m["daily_vol"] = daily_ret.std()
                m["ann_vol"] = m["daily_vol"] * (ANN_FACTOR ** 0.5)
                m["sharpe"] = (daily_ret.mean() / m["daily_vol"] * (ANN_FACTOR ** 0.5)
                               if m["daily_vol"] > 0 else 0)

        # --- 买入持有基准 ---
        if "buyhold_nav" in nav.columns and not nav.empty:
            m["buyhold_return"] = nav["buyhold_nav"].iloc[-1] - 1
            bh_peak = nav["buyhold_nav"].cummax()
            bh_dd = (nav["buyhold_nav"] - bh_peak) / bh_peak
            m["buyhold_max_dd"] = bh_dd.min()
            if "buyhold_return" in nav.columns:
                bh_ret = nav["buyhold_return"]
                bh_vol = bh_ret.std()
                m["buyhold_sharpe"] = (bh_ret.mean() / bh_vol * (ANN_FACTOR ** 0.5)
                                       if bh_vol > 0 else 0)
            m["excess_vs_buyhold"] = m.get("total_return", 0) - m["buyhold_return"]

        # --- 沪深300基准 ---
        if "benchmark_nav" in nav.columns:
            bench_valid = nav.dropna(subset=["benchmark_nav"])
            if not bench_valid.empty:
                m["benchmark_return"] = bench_valid["benchmark_nav"].iloc[-1] - 1
                bench_peak = bench_valid["benchmark_nav"].cummax()
                bench_dd = (bench_valid["benchmark_nav"] - bench_peak) / bench_peak
                m["benchmark_max_dd"] = bench_dd.min()
                m["excess_vs_benchmark"] = m.get("total_return", 0) - m["benchmark_return"]
                if "excess_return" in nav.columns:
                    excess_daily = nav["excess_return"].dropna()
                    te = excess_daily.std()
                    m["tracking_error"] = te * (ANN_FACTOR ** 0.5)
                    m["information_ratio"] = (excess_daily.mean() / te * (ANN_FACTOR ** 0.5)
                                              if te > 0 else 0)

        # --- 交易统计 ---
        if not trades.empty:
            dir_col = "direction" if "direction" in trades.columns else None
            pnl_col = "pnl" if "pnl" in trades.columns else None

            if dir_col and pnl_col:
                sells = trades[trades[dir_col] == "SELL"]
                wins = (sells[pnl_col] > 0).sum()
                losses = (sells[pnl_col] <= 0).sum()
                total_closed = wins + losses
                m["n_trades"] = total_closed
                m["win_rate"] = wins / total_closed if total_closed > 0 else 0
                m["n_wins"] = int(wins)
                m["n_losses"] = int(losses)

                if wins > 0:
                    m["avg_win"] = sells[sells[pnl_col] > 0][pnl_col].mean()
                if losses > 0:
                    m["avg_loss"] = sells[sells[pnl_col] <= 0][pnl_col].mean()
                if wins > 0 and losses > 0:
                    m["profit_loss_ratio"] = abs(m["avg_win"] / m["avg_loss"])
                    m["expectancy"] = (m["win_rate"] * m["avg_win"]
                                       + (1 - m["win_rate"]) * m["avg_loss"])

                # 手续费
                cost_cols = [c for c in ["commission", "stamp_tax"] if c in trades.columns]
                if cost_cols:
                    m["total_cost"] = trades[cost_cols].sum().sum()
                    m["net_pnl"] = trades[pnl_col].sum() - m.get("total_cost", 0)

                # 持有期
                if "trade_date" in trades.columns and dir_col:
                    hold_days = _calc_holding_days(trades)
                    if hold_days:
                        m["avg_hold_days"] = np.mean(hold_days)
                        m["max_hold_days"] = max(hold_days)
                        m["min_hold_days"] = min(hold_days)

        # --- 月度收益 ---
        if not nav.empty and "date" in nav.columns and "return" in nav.columns:
            m["monthly_returns"] = _calc_monthly_returns(nav)

        self._metrics = m
        return m

    def get_drawdown_series(self) -> pd.Series:
        """策略回撤序列"""
        asset_col = "nav" if "nav" in self.nav.columns else "total_asset"
        peak = self.nav[asset_col].cummax()
        return (self.nav[asset_col] - peak) / peak

    def get_buyhold_drawdown_series(self) -> Optional[pd.Series]:
        """买入持有回撤序列"""
        if "buyhold_nav" not in self.nav.columns:
            return None
        peak = self.nav["buyhold_nav"].cummax()
        return (self.nav["buyhold_nav"] - peak) / peak

    # ======================== 多股票分析 ========================
    def get_per_stock_stats(self) -> pd.DataFrame:
        """
        按个股统计交易表现

        Returns:
            DataFrame: 每只股票一行, 列含 交易次数/胜率/总盈亏/平均持有天数
        """
        if self.trades.empty:
            return pd.DataFrame()

        trades = self.trades.copy()
        if "ts_code" not in trades.columns or "direction" not in trades.columns:
            return pd.DataFrame()

        rows = []
        for ts_code, group in trades.groupby("ts_code"):
            sells = group[group["direction"] == "SELL"]
            buys = group[group["direction"] == "BUY"]
            n_sells = len(sells)
            n_buys = len(buys)

            if n_sells == 0:
                continue

            pnl_col = "pnl" if "pnl" in sells.columns else None
            if pnl_col is None:
                continue

            wins = (sells[pnl_col] > 0).sum()
            losses = (sells[pnl_col] <= 0).sum()
            total_pnl = sells[pnl_col].sum()
            total_cost = 0
            for c in ["commission", "stamp_tax"]:
                if c in group.columns:
                    total_cost += group[c].sum()

            # 持有天数
            hold_days = _calc_holding_days(group)
            avg_hold = np.mean(hold_days) if hold_days else 0

            rows.append({
                "ts_code": ts_code,
                "买入次数": n_buys,
                "卖出次数": n_sells,
                "胜率": wins / n_sells if n_sells > 0 else 0,
                "盈利笔数": int(wins),
                "亏损笔数": int(losses),
                "总盈亏": total_pnl,
                "总手续费": total_cost,
                "净盈亏": total_pnl - total_cost,
                "平均持有天数": avg_hold,
            })

        df = pd.DataFrame(rows)
        if not df.empty:
            df = df.sort_values("总盈亏", ascending=False).reset_index(drop=True)
        return df

    def get_per_stock_monthly_pnl(self) -> pd.DataFrame:
        """
        按个股 + 月份统计已实现盈亏

        Returns:
            DataFrame 透视表: 行=年月, 列=ts_code, 值=当月该股票卖出盈亏合计
        """
        if self.trades.empty:
            return pd.DataFrame()

        trades = self.trades.copy()
        if "trade_date" not in trades.columns or "pnl" not in trades.columns:
            return pd.DataFrame()

        # 只看卖出 (有 pnl)
        sells = trades[trades.get("direction", "") == "SELL"].copy()
        if sells.empty:
            return pd.DataFrame()

        sells["date"] = pd.to_datetime(
            sells["trade_date"].astype(str), format="%Y%m%d", errors="coerce"
        )
        sells = sells.dropna(subset=["date"])
        sells["year_month"] = sells["date"].dt.to_period("M").astype(str)

        pivot = sells.pivot_table(
            index="year_month",
            columns="ts_code",
            values="pnl",
            aggfunc="sum",
            fill_value=0,
        )
        return pivot


def _calc_holding_days(trades: pd.DataFrame) -> list:
    """计算每笔交易的持有天数 (BUY -> 对应 SELL)"""
    hold_days = []
    date_col = "trade_date"
    dir_col = "direction"

    # 转为日期格式
    dates = pd.to_datetime(trades[date_col].astype(str), format="%Y%m%d", errors="coerce")
    buys = []
    for _, row in trades.iterrows():
        if row[dir_col] == "BUY":
            buys.append(dates[_])
        elif row[dir_col] == "SELL" and buys:
            buy_date = buys.pop(0)
            sell_date = dates[_]
            delta = (sell_date - buy_date).days
            if delta >= 0:
                hold_days.append(delta)
    return hold_days


def _calc_monthly_returns(nav: pd.DataFrame) -> pd.DataFrame:
    """计算月度收益率, 返回透视表 (年 x 月)"""
    df = nav.copy()
    df["date"] = pd.to_datetime(df["date"].astype(str), format="%Y%m%d", errors="coerce")
    df = df.dropna(subset=["date"])
    df["year"] = df["date"].dt.year
    df["month"] = df["date"].dt.month

    # 每月最后一个交易日的累计净值
    monthly_nav = df.groupby(["year", "month"])["return"].apply(
        lambda x: (1 + x).prod() - 1
    ).reset_index()

    # 透视成 年 x 月 表
    pivot = monthly_nav.pivot(index="year", columns="month", values="return")
    # 补齐 1-12 列
    for m in range(1, 13):
        if m not in pivot.columns:
            pivot[m] = np.nan
    pivot = pivot[sorted(pivot.columns)]

    # 年度合计
    pivot["全年"] = (1 + pivot.fillna(0)).prod(axis=1) - 1
    return pivot


def load_report(nav_path: str, trades_path: str) -> BacktestReport:
    """从 CSV 加载回测报告"""
    nav = pd.read_csv(nav_path)
    trades = pd.read_csv(trades_path)
    return BacktestReport(nav=nav, trades=trades)


def find_default_report() -> tuple:
    """查找默认的回测结果文件路径"""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(root, "output")
    nav_path = os.path.join(output_dir, "backtest_nav.csv")
    trades_path = os.path.join(output_dir, "backtest_trades.csv")
    return nav_path, trades_path
