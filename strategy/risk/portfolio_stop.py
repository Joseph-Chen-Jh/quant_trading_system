"""
组合级回撤止损 (Portfolio Drawdown Stop)

与个股止损 (TrailingStopLoss) 互补:
    - 个股止损: 管单只股票的回撤
    - 组合止损: 管整个组合的回撤 (多只股票同时小亏会累积成组合级回撤)

逻辑:
    1. 跟踪组合净值历史峰值 (peak_nav)
    2. 当 (peak_nav - current_nav) / peak_nav > drawdown_threshold 时触发:
       - 清仓所有持仓
       - 暂停开新仓
    3. 暂停后, 等待 recovery_days 个交易日后自动恢复开仓

参数:
    - drawdown_threshold: 触发回撤阈值 (默认 0.12 = 12%)
    - recovery_days: 恢复开仓需要等待的交易日数 (默认 20 = 约 1 个月)

注意:
    恢复条件用"等待 N 天"而非"从低点反弹 X%", 因为清仓后全仓现金,
    组合净值不再变化, "反弹"条件永远无法满足。
"""
import pandas as pd
from loguru import logger


class PortfolioDrawdownStop:
    """组合级回撤止损"""

    def __init__(
        self,
        drawdown_threshold: float = 0.12,
        recovery_days: int = 20,
    ):
        """
        Args:
            drawdown_threshold: 触发回撤阈值 (如 0.12 = 从峰值回撤 12% 触发)
            recovery_days: 恢复开仓需要等待的交易日数 (如 20 = 约 1 个月)
        """
        self.drawdown_threshold = drawdown_threshold
        self.recovery_days = recovery_days

        # 状态
        self.peak_nav: float = 0.0          # 历史最高净值
        self.is_halted: bool = False         # 是否处于暂停开仓状态
        self.halt_date: str = None           # 暂停开始日期
        self.halt_day_count: int = 0         # 暂停已过的交易日数
        self.n_triggers: int = 0             # 触发次数

    def check_and_update(self, account, trade_date: str) -> bool:
        """
        每日收盘后调用, 更新峰值, 判断是否触发清仓或恢复

        Args:
            account: VirtualAccount 实例 (需有 total_asset 属性)
            trade_date: 当前交易日
        Returns:
            True = 本次触发清仓 (需要生成 SELL 信号)
            False = 未触发
        """
        current_nav = account.total_asset
        triggered = False

        if not self.is_halted:
            # 正常状态: 更新峰值
            if current_nav > self.peak_nav:
                self.peak_nav = current_nav

            # 检查回撤
            if self.peak_nav > 0:
                drawdown = (self.peak_nav - current_nav) / self.peak_nav
                if drawdown >= self.drawdown_threshold:
                    self.is_halted = True
                    self.halt_date = trade_date
                    self.halt_day_count = 0
                    self.n_triggers += 1
                    triggered = True
                    logger.warning(
                        f"组合回撤止损触发 @ {trade_date}: "
                        f"峰值 {self.peak_nav:,.0f}, 当前 {current_nav:,.0f}, "
                        f"回撤 {drawdown:.2%} >= {self.drawdown_threshold:.2%}, "
                        f"清仓并暂停开仓 {self.recovery_days} 天"
                    )
        else:
            # 暂停状态: 计数, 检查是否到恢复天数
            self.halt_day_count += 1
            if self.halt_day_count >= self.recovery_days:
                self.is_halted = False
                logger.info(
                    f"组合回撤止损恢复 @ {trade_date}: "
                    f"已暂停 {self.halt_day_count} 个交易日, 恢复开仓, "
                    f"峰值重置为 {current_nav:,.0f}"
                )
                # 恢复后重置峰值 (避免刚恢复就因小回撤再次触发)
                self.peak_nav = current_nav
                self.halt_date = None
                self.halt_day_count = 0

        return triggered

    def can_open_position(self) -> bool:
        """是否允许开新仓"""
        return not self.is_halted

    def generate_liquidation_signals(self, account, trade_date: str) -> list:
        """
        生成清仓信号 (所有持仓的 SELL)

        Returns:
            [{"ts_code": ..., "action": "SELL", "price": ...}, ...]
        """
        signals = []
        for ts_code, position in account.positions.items():
            if position.volume > 0:
                signals.append({
                    "ts_code": ts_code,
                    "action": "SELL",
                    "price": float(position.current_price),
                    "reason": f"portfolio_drawdown_stop ({self.drawdown_threshold:.0%})",
                })
        return signals

    def get_stats(self) -> dict:
        """返回统计信息"""
        return {
            "drawdown_threshold": self.drawdown_threshold,
            "recovery_pct": self.recovery_pct,
            "n_triggers": self.n_triggers,
            "is_halted": self.is_halted,
            "peak_nav": self.peak_nav,
            "trough_nav": self.trough_nav,
        }
