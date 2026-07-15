"""命令行参数解析"""
import argparse


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器"""
    parser = argparse.ArgumentParser(description="量化交易系统")
    parser.add_argument(
        "--mode",
        choices=["update_data", "backtest", "backtest-pool", "fetch-pool",
                 "backtest-pe", "simulation", "report", "full"],
        default="simulation", help="运行模式"
    )
    parser.add_argument("--date", help="交易日期 YYYYMMDD")
    parser.add_argument("--init-db", action="store_true", help="初始化数据库")

    # 单股票回测参数
    parser.add_argument("--stock", default="000001.SZ", help="单股票回测 ts_code")
    parser.add_argument("--start", default="20240101", help="回测起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="回测截止日期 YYYYMMDD (默认到最新)")
    parser.add_argument("--short", type=int, default=5, help="短期均线周期")
    parser.add_argument("--long", type=int, default=20, help="长期均线周期")
    parser.add_argument(
        "--adx-threshold", type=float, default=0.0,
        help="ADX 过滤阈值 (默认 0=不过滤; 25=只趋势明确时买入)",
    )

    # 组合回测参数
    parser.add_argument("--pool", default="default", help="股票池名称 (见 config/stock_pool.yaml)")
    parser.add_argument(
        "--stop-loss", default="trailing", choices=["trailing", "fixed", "none"],
        help="止损类型: trailing=追踪止损(默认), fixed=固定止损, none=禁用",
    )
    parser.add_argument(
        "--stop-pct", type=float, default=None,
        help="止损比例 (覆盖默认值: trailing=0.08, fixed=0.10)",
    )

    # PE 选股策略参数
    parser.add_argument(
        "--quantile", type=float, default=0.3,
        help="PE 分位数阈值 (默认 0.3, 只选历史 30%% 分位以下的)",
    )
    parser.add_argument(
        "--lookback", type=int, default=3,
        help="PE 历史回看年数 (默认 3)",
    )
    parser.add_argument(
        "--top-n", type=int, default=3,
        help="最多持有股票数 (默认 3)",
    )
    parser.add_argument(
        "--freq", default="monthly", choices=["monthly", "quarterly"],
        help="调仓频率 (默认 monthly)",
    )

    # 动态波动率筛选参数
    parser.add_argument(
        "--dynamic-vol", action="store_true",
        help="启用动态波动率筛选 (每月从候选池选波动率前 N 只作为可买入池)",
    )
    parser.add_argument(
        "--vol-lookback", type=int, default=60,
        help="波动率计算回看天数 (默认 60 交易日)",
    )
    parser.add_argument(
        "--vol-top", type=int, default=10,
        help="动态选波动率前 N 只 (默认 10)",
    )

    # 市场环境过滤参数
    parser.add_argument(
        "--market-filter", type=str, default=None,
        choices=["price_above_ma", "ma_slope_up", "both"],
        help="市场环境过滤规则 (沪深300): price_above_ma=价格>MA60, "
             "ma_slope_up=MA60上行, both=两者同时满足",
    )

    # 动态仓位管理参数
    parser.add_argument(
        "--position-scaler", action="store_true",
        help="启用动态仓位管理 (基于沪深300 MA60 偏离度调整开仓资金比例)",
    )

    # 多策略并行参数
    parser.add_argument(
        "--rsi", action="store_true",
        help="启用 RSI 均值回归策略 (与 MA 趋势策略并行, 信号叠加)",
    )

    # 组合级回撤止损参数
    parser.add_argument(
        "--portfolio-dd", type=float, default=None,
        help="组合级回撤止损阈值 (如 0.12 = 从峰值回撤 12%% 清仓暂停), 不填=不启用",
    )

    return parser
