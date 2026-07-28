"""
量化交易系统 - 主入口

用法:
    python main.py --mode update_data    # 更新数据
    python main.py --mode backtest       # 单股票回测
    python main.py --mode backtest-pool  # 多股票组合回测
    python main.py --mode backtest-pe    # PE 选股回测
    python main.py --mode fetch-pool     # 拉取股票池数据
    python main.py --mode simulation     # 运行模拟交易
    python main.py --mode report         # 生成绩效报告
    python main.py --mode full           # 一键全流程
    streamlit run monitor/dashboard.py   # 启动监控面板
"""
import os
import sys

# Windows 控制台默认 GBK 编码, 中文输出会乱码
# 在任何其他 import 之前强制重配置 stdout/stderr 为 UTF-8
if sys.platform == "win32":
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# 确保项目根目录在 path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from loguru import logger
from config.log_config import logger  # noqa: F401 — 初始化日志配置
from config.settings import DATABASE_PATH
from data.storage.models import init_database
from cli.parser import (
    build_parser, build_single_backtest_config,
    build_backtest_config, build_pe_config,
)
from cli.data_commands import cmd_update_data, cmd_fetch_pool
from cli.backtest_commands import cmd_backtest, cmd_backtest_pool, cmd_backtest_pe
from cli.sim_commands import cmd_simulation, cmd_report


def main():
    args = build_parser().parse_args()

    # 初始化数据库
    if args.init_db:
        init_database()
        logger.info(f"数据库已初始化: {DATABASE_PATH}")

    # 路由分发
    if args.mode == "update_data":
        cmd_update_data()

    elif args.mode == "backtest":
        cfg = build_single_backtest_config(args)
        cmd_backtest(cfg)

    elif args.mode == "backtest-pool":
        cfg = build_backtest_config(args)
        cmd_backtest_pool(cfg)

    elif args.mode == "fetch-pool":
        cmd_fetch_pool(pool_name=args.pool, start_date=args.start)

    elif args.mode == "backtest-pe":
        cfg = build_pe_config(args)
        cmd_backtest_pe(cfg)

    elif args.mode == "simulation":
        cmd_simulation()

    elif args.mode == "report":
        cmd_report()

    elif args.mode == "full":
        logger.info("一键全流程 — 待串联各模块")
        cmd_update_data()
        cmd_backtest(build_single_backtest_config(args))
        cmd_simulation()
        cmd_report()


if __name__ == "__main__":
    main()
