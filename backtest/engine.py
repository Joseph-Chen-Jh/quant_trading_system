"""
回测引擎 (基于 Backtrader 封装)
"""
import backtrader as bt
import pandas as pd
from datetime import datetime
from loguru import logger
from config.settings import BACKTEST_INITIAL_CASH, BACKTEST_COMMISSION


class BacktestEngine:
    """回测引擎"""

    def __init__(self, initial_cash: float = None, commission: float = None):
        self.cerebro = bt.Cerebro()
        self.cerebro.broker.setcash(initial_cash or BACKTEST_INITIAL_CASH)
        self.cerebro.broker.setcommission(commission=commission or BACKTEST_COMMISSION)

        # 内置分析器
        self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
        self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")
        self.cerebro.addanalyzer(bt.analyzers.Returns, _name="returns")
        self.cerebro.addanalyzer(bt.analyzers.TradeAnalyzer, _name="trades")
        self.cerebro.addanalyzer(bt.analyzers.AnnualReturn, _name="annual_return")

    def add_strategy(self, strategy_cls, **params):
        """添加策略"""
        self.cerebro.addstrategy(strategy_cls, **params)

    def add_data(self, df: pd.DataFrame, name: str = "stock"):
        """
        添加行情数据

        期望 df 列: trade_date, open, high, low, close, volume
        """
        df = df.copy()
        if "trade_date" in df.columns:
            df["trade_date"] = pd.to_datetime(df["trade_date"])
            df = df.set_index("trade_date")

        for col in ["open", "high", "low", "close", "volume"]:
            if col not in df.columns:
                df[col] = float("nan")

        data = bt.feeds.PandasData(dataname=df, open="open", high="high",
                                   low="low", close="close", volume="volume")
        self.cerebro.adddata(data, name=name)

    def run(self) -> dict:
        """执行回测并返回结果"""
        start_value = self.cerebro.broker.getvalue()
        logger.info(f"回测初始资金: {start_value:,.0f}")

        results = self.cerebro.run()
        end_value = self.cerebro.broker.getvalue()

        strat = results[0]
        report = {
            "initial_value": start_value,
            "final_value": end_value,
            "total_return": (end_value - start_value) / start_value,
            "sharpe": _safe_analyzer(strat.analyzers.sharpe, "sharperatio"),
            "max_drawdown": _safe_analyzer(strat.analyzers.drawdown, "max.drawdown"),
            "returns": _safe_analyzer(strat.analyzers.returns, "rnorm100"),
            "trade_stats": _parse_trade_analyzer(strat.analyzers.trades),
        }

        logger.info(f"回测完成: 收益率={report['total_return']:.2%}, 夏普={report['sharpe']:.2f}")
        return report

    def plot(self):
        """绘图 (需要 matplotlib)"""
        self.cerebro.plot(style="candlestick")


def _safe_analyzer(analyzer, key: str, default=0.0):
    """安全提取分析器值"""
    try:
        val = analyzer.get_analysis()
        if isinstance(val, dict):
            return val.get(key, default) or default
        return val or default
    except Exception:
        return default


def _parse_trade_analyzer(analyzer) -> dict:
    """解析交易分析器"""
    try:
        analysis = analyzer.get_analysis()
        return {
            "total_trades": analysis.get("total", {}).get("total", 0),
            "won": analysis.get("won", {}).get("total", 0),
            "lost": analysis.get("lost", {}).get("total", 0),
        }
    except Exception:
        return {"total_trades": 0, "won": 0, "lost": 0}
