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
from cli.parser import build_parser
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
        cmd_backtest(
            ts_code=args.stock,
            start_date=args.start,
            end_date=args.end,
            short_window=args.short,
            long_window=args.long,
        )

    elif args.mode == "backtest-pool":
        cmd_backtest_pool(
            pool_name=args.pool,
            start_date=args.start,
            end_date=args.end,
            short_window=args.short,
            long_window=args.long,
            stop_loss_type=args.stop_loss,
            stop_loss_pct=args.stop_pct,
            adx_threshold=args.adx_threshold,
            dynamic_vol=args.dynamic_vol,
            vol_lookback=args.vol_lookback,
            vol_top=args.vol_top,
            market_filter_rule=args.market_filter,
            use_position_scaler=args.position_scaler,
            use_rsi=args.rsi,
            portfolio_dd_threshold=args.portfolio_dd,
        )

    elif args.mode == "fetch-pool":
        cmd_fetch_pool(pool_name=args.pool, start_date=args.start)

    elif args.mode == "backtest-pe":
        cmd_backtest_pe(
            pool_name=args.pool,
            start_date=args.start,
            end_date=args.end,
            quantile_threshold=args.quantile,
            lookback_years=args.lookback,
            top_n=args.top_n,
            rebalance_freq=args.freq,
        )

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
