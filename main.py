"""
量化交易系统 - 主入口

用法:
    python main.py --mode update_data    # 更新数据
    python main.py --mode backtest       # 运行回测
    python main.py --mode simulation     # 运行模拟交易
    python main.py --mode report         # 生成绩效报告
    python main.py --mode full           # 一键全流程
    streamlit run monitor/dashboard.py   # 启动监控面板
"""
import argparse
import os
import sys

# 确保项目根目录在 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger
from config.log_config import logger  # noqa: F401 — 初始化日志配置
from config.settings import DATABASE_PATH
from data.storage.models import init_database
from simulation.account import VirtualAccount
from simulation.order_manager import OrderManager
from simulation.scheduler import SimulationScheduler
from monitor.reporter import ReportGenerator
from monitor.risk_monitor import RiskMonitor


def cmd_update_data():
    """增量更新数据"""
    from data.fetcher.pipeline import pipeline_update
    pipeline_update()


def cmd_backtest():
    """运行回测 (示例)"""
    logger.info("回测模块 — 需提供策略和数据")
    # TODO: 加载数据 + 运行 BacktestEngine


def cmd_simulation():
    """运行模拟交易"""
    logger.info("启动模拟交易系统...")

    account = VirtualAccount()
    om = OrderManager(account)
    scheduler = SimulationScheduler(account, om)

    # 示例: 空跑一天
    report = scheduler.run_daily(
        trade_date="20260606",
        signals=[],
        prices={},
    )

    # 输出摘要
    rg = ReportGenerator(account, output_dir=os.path.dirname(os.path.abspath(__file__)))
    summary = rg.generate_text_summary()
    print(summary)

    # 风控检查
    monitor = RiskMonitor(account)
    result = monitor.check_all()
    logger.info(f"风控状态: {result['status']}")
    for alert in result["alerts"]:
        logger.warning(alert)


def cmd_report():
    """生成绩效报告"""
    logger.info("报告模块 — 需先运行模拟交易产生记录")


def main():
    parser = argparse.ArgumentParser(description="量化交易系统")
    parser.add_argument("--mode", choices=["update_data", "backtest", "simulation", "report", "full"],
                        default="simulation", help="运行模式")
    parser.add_argument("--date", help="交易日期 YYYYMMDD")
    parser.add_argument("--init-db", action="store_true", help="初始化数据库")
    args = parser.parse_args()

    # 初始化数据库
    if args.init_db:
        engine = init_database()
        logger.info(f"数据库已初始化: {DATABASE_PATH}")

    # 路由
    if args.mode == "update_data":
        cmd_update_data()
    elif args.mode == "backtest":
        cmd_backtest()
    elif args.mode == "simulation":
        cmd_simulation()
    elif args.mode == "report":
        cmd_report()
    elif args.mode == "full":
        logger.info("一键全流程 — 待串联各模块")
        cmd_update_data()
        cmd_backtest()
        cmd_simulation()
        cmd_report()


if __name__ == "__main__":
    main()
