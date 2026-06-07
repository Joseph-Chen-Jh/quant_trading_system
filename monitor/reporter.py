"""
绩效报告生成器
"""
import os
from datetime import datetime
import pandas as pd
from loguru import logger
from simulation.account import VirtualAccount


class ReportGenerator:
    """生成交易绩效报告"""

    def __init__(self, account: VirtualAccount, output_dir: str = None):
        self.account = account
        self.output_dir = output_dir or "."

    def generate_text_summary(self) -> str:
        """生成纯文本摘要"""
        s = self.account.get_summary()
        lines = [
            "=" * 50,
            f"  量化交易系统 — 绩效报告",
            f"  生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "=" * 50,
            "",
            f"  总资产:      ¥{s['total_asset']:>15,.0f}",
            f"  可用资金:    ¥{s['available_cash']:>15,.0f}",
            f"  累计收益率:  {s['total_return']*100:>15.2f}%",
            f"  持仓数:      {s['position_count']:>15}",
            "",
        ]

        if s["positions"]:
            lines.append("-" * 50)
            lines.append("  持仓明细:")
            lines.append(f"  {'代码':<12} {'股数':>8} {'成本':>8} {'现价':>8} {'盈亏':>12} {'盈亏%':>8}")
            for p in s["positions"]:
                lines.append(
                    f"  {p['ts_code']:<12} {p['volume']:>8} {p['cost_price']:>8.2f} "
                    f"{p['current_price']:>8.2f} {p['pnl']:>12,.0f} {p['pnl_pct']*100:>7.2f}%"
                )

        return "\n".join(lines)

    def save_text_report(self, filename: str = None):
        """保存文本报告"""
        if filename is None:
            filename = f"report_{datetime.now().strftime('%Y%m%d')}.txt"
        path = os.path.join(self.output_dir, filename)
        content = self.generate_text_summary()
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)
        logger.info(f"报告已保存: {path}")
        return path

    def to_dataframe(self) -> pd.DataFrame:
        """导出净值序列为 DataFrame"""
        if not self.account.daily_nav:
            return pd.DataFrame()
        return pd.DataFrame(self.account.daily_nav)
