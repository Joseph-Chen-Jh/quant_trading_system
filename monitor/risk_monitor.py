"""
风险监控模块
"""
from loguru import logger
from config.settings import MAX_DRAWDOWN, MAX_POSITION_PCT, MAX_TOTAL_POSITION
from simulation.account import VirtualAccount


class RiskMonitor:
    """实时风险监控"""

    def __init__(self, account: VirtualAccount):
        self.account = account
        self.alerts = []

    def check_all(self) -> dict:
        """执行全部风控检查"""
        self.alerts = []
        summary = self.account.get_summary()

        self._check_drawdown(summary)
        self._check_concentration(summary)
        self._check_stop_loss()

        return {
            "status": "WARN" if self.alerts else "OK",
            "alerts": self.alerts,
        }

    def _check_drawdown(self, summary: dict):
        if summary["total_return"] < -MAX_DRAWDOWN:
            msg = f"🚨 总回撤 {summary['total_return']*100:.2f}% 超过警戒线 {MAX_DRAWDOWN*100:.0f}%"
            logger.warning(msg)
            self.alerts.append(msg)

    def _check_concentration(self, summary: dict):
        total = summary["total_asset"]
        for p in summary["positions"]:
            ratio = p["market_value"] / total if total > 0 else 0
            if ratio > MAX_POSITION_PCT:
                msg = f"⚠️ {p['ts_code']} 仓位 {ratio*100:.1f}% 超过单票上限 {MAX_POSITION_PCT*100:.0f}%"
                logger.warning(msg)
                self.alerts.append(msg)

        position_pct = self.account.position_value / total if total > 0 else 0
        if position_pct > MAX_TOTAL_POSITION:
            msg = f"⚠️ 总仓位 {position_pct*100:.1f}% 超过上限 {MAX_TOTAL_POSITION*100:.0f}%"
            logger.warning(msg)
            self.alerts.append(msg)

    def _check_stop_loss(self):
        for code, pos in self.account.positions.items():
            if pos.profit_loss_pct < -0.10:  # 硬止损
                msg = f"🔴 {code} 浮亏 {pos.profit_loss_pct*100:.2f}% 触发止损预警"
                logger.warning(msg)
                self.alerts.append(msg)
