"""模拟交易和报告命令"""
import os
from loguru import logger

from simulation.account import VirtualAccount
from simulation.order_manager import OrderManager
from simulation.scheduler import SimulationScheduler
from monitor.reporter import ReportGenerator
from monitor.risk_monitor import RiskMonitor


def cmd_simulation():
    """运行模拟交易"""
    logger.info("启动模拟交易系统...")

    account = VirtualAccount()
    om = OrderManager(account)
    scheduler = SimulationScheduler(account, om)

    # 示例: 空跑一天
    scheduler.run_daily(
        trade_date="20260606",
        signals=[],
        prices={},
    )

    # 输出摘要
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rg = ReportGenerator(account, output_dir=base_dir)
    print(rg.generate_text_summary())

    # 风控检查
    monitor = RiskMonitor(account)
    result = monitor.check_all()
    logger.info(f"风控状态: {result['status']}")
    for alert in result["alerts"]:
        logger.warning(alert)


def cmd_report():
    """生成绩效报告"""
    logger.info("报告模块 — 需先运行模拟交易产生记录")
