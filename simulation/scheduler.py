"""
模拟交易调度器
"""
from typing import Dict, List
import pandas as pd
from loguru import logger
from simulation.account import VirtualAccount
from simulation.order_manager import OrderManager


class SimulationScheduler:
    """每日模拟交易调度"""

    def __init__(self, account: VirtualAccount, order_manager: OrderManager):
        self.account = account
        self.om = order_manager

    def run_daily(self, trade_date: str, signals: List[Dict],
                  prices: Dict[str, float], amounts: Dict[str, float] = None) -> dict:
        """
        执行一日模拟交易

        Args:
            trade_date: 交易日 (YYYYMMDD)
            signals: 策略生成的信号列表
            prices:   {ts_code: close_price}
            amounts:  {ts_code: daily_amount}
        Returns:
            当日执行报告
        """
        logger.info(f"--- 模拟交易日: {trade_date} ---")

        # 0. 设置当前交易日 (供交易记录使用)
        self.account.set_trade_date(trade_date)

        # 1. 更新持仓市值
        self.account.update_prices(prices)

        # 2. 处理信号
        self.om.reset_daily()
        executions = self.om.process_signals(signals, prices, amounts or {})

        # 3. 日末结算
        self.account.end_of_day(trade_date)

        # 4. 生成报告
        filled = [e for e in executions if e["result"] == "FILLED"]
        skipped = [e for e in executions if e["result"] not in ("FILLED",)]
        summary = self.account.get_summary()

        report = {
            "trade_date": trade_date,
            "signals_total": len(signals),
            "filled": len(filled),
            "skipped": len(skipped),
            "total_asset": summary["total_asset"],
            "total_return": summary["total_return"],
            "cash": summary["cash"],
            "position_count": summary["position_count"],
            "executions": executions,
            "skip_reasons": [s.get("reason", "") for s in skipped if s.get("reason")],
        }

        logger.info(f"完成: 成交{len(filled)}笔, 当前总资产 {summary['total_asset']:,.0f}")
        return report

    def run_backfill(self, df: pd.DataFrame, strategy_signal_fn):
        """
        历史回填模拟 —— 在已有日线数据上跑模拟交易

        Args:
            df: 全市场日线 (ts_code, trade_date, close, amount)
            strategy_signal_fn: 函数 (date_str) -> List[signal_dict]
        """
        dates = sorted(df["trade_date"].unique())
        reports = []

        for date in dates:
            daily = df[df["trade_date"] == date]
            prices = dict(zip(daily["ts_code"], daily["close"]))
            amounts = dict(zip(daily["ts_code"], daily["amount"])) if "amount" in daily.columns else {}

            signals = strategy_signal_fn(date)
            report = self.run_daily(date, signals, prices, amounts)
            reports.append(report)

        return reports
