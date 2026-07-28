"""命令行参数解析

提供两种获取参数的方式:
    - build_parser(): 返回 argparse.ArgumentParser, 用于 CLI 解析 (向后兼容)
    - build_config(args): 将 argparse Namespace 转成结构化配置对象 (推荐)
"""
import argparse
from config.backtest_config import (
    BacktestConfig, MAConfig, RSIConfig, VolSelectorConfig, RiskConfig,
    SingleBacktestConfig, PEConfig,
)


def build_parser() -> argparse.ArgumentParser:
    """构建 CLI 参数解析器 (参数定义保持不变, 向后兼容)"""
    parser = argparse.ArgumentParser(description="量化交易系统")
    parser.add_argument(
        "--mode",
        choices=["update_data", "backtest", "backtest-pool", "fetch-pool",
                 "backtest-pe", "simulation", "report", "full"],
        default="simulation", help="运行模式"
    )
    parser.add_argument("--date", help="交易日期 YYYYMMDD")
    parser.add_argument("--init-db", action="store_true", help="初始化数据库")

    # === 单股票回测参数 ===
    parser.add_argument("--stock", default="000001.SZ", help="单股票回测 ts_code")
    parser.add_argument("--start", default="20240101", help="回测起始日期 YYYYMMDD")
    parser.add_argument("--end", default=None, help="回测截止日期 YYYYMMDD (默认到最新)")
    parser.add_argument("--short", type=int, default=5, help="短期均线周期")
    parser.add_argument("--long", type=int, default=20, help="长期均线周期")
    parser.add_argument(
        "--adx-threshold", type=float, default=0.0,
        help="ADX 过滤阈值 (默认 0=不过滤; 25=只趋势明确时买入)",
    )

    # === 组合回测参数 ===
    parser.add_argument("--pool", default="default", help="股票池名称 (见 config/stock_pool.yaml)")
    parser.add_argument(
        "--strategy", default="ma", choices=["ma", "rsi"],
        help="组合回测策略: ma=MA双均线(默认), rsi=RSI均值回归",
    )
    parser.add_argument(
        "--stop-loss", default="trailing", choices=["trailing", "fixed", "time", "combo", "none"],
        help="止损类型: trailing=追踪止损(默认), fixed=固定止损, time=时间止损, combo=组合止损, none=禁用",
    )
    parser.add_argument(
        "--stop-pct", type=float, default=None,
        help="止损比例 (覆盖默认值: trailing=0.08, fixed=0.10)",
    )
    parser.add_argument(
        "--max-hold-days", type=int, default=20,
        help="时间止损/组合止损的最大持有交易日数 (默认 20)",
    )

    # === RSI 策略参数 (strategy=rsi 时生效) ===
    parser.add_argument(
        "--rsi-period", type=int, default=14,
        help="RSI 计算周期 (默认 14, Wilder 标准)",
    )
    parser.add_argument(
        "--oversold", type=float, default=30.0,
        help="RSI 超卖阈值, 上穿时买入 (默认 30, 固定模式)",
    )
    parser.add_argument(
        "--overbought", type=float, default=70.0,
        help="RSI 超买阈值, 下穿时卖出 (默认 70, 固定模式)",
    )
    parser.add_argument(
        "--adaptive", action="store_true",
        help="RSI 启用自适应分位数阈值 (用滚动 lookback 天 RSI 的 low_q/high_q 分位数替代固定阈值)",
    )
    parser.add_argument(
        "--rsi-lookback", type=int, default=60,
        help="自适应模式的滚动窗口天数 (默认 60)",
    )
    parser.add_argument(
        "--low-q", type=float, default=0.10,
        help="自适应模式超卖分位数 (默认 0.10)",
    )
    parser.add_argument(
        "--high-q", type=float, default=0.90,
        help="自适应模式超买分位数 (默认 0.90)",
    )
    parser.add_argument(
        "--vol-grouped", action="store_true",
        help="RSI 启用波动率分组模式 (高波动>40%用20/80, 中波动30-40%用30/70, 低波动<30%跳过)",
    )
    parser.add_argument(
        "--rsi-vol-lookback", type=int, default=60,
        help="波动率分组模式的波动率回看天数 (默认 60)",
    )
    parser.add_argument(
        "--vol-high", type=float, default=0.40,
        help="波动率分组模式高波动阈值 (默认 0.40, 年化)",
    )
    parser.add_argument(
        "--vol-low", type=float, default=0.30,
        help="波动率分组模式低波动阈值 (默认 0.30, 年化)",
    )
    parser.add_argument(
        "--multi-period", action="store_true",
        help="RSI 启用多周期共振模式 (RSI(14)上穿30买入 + RSI(21)<阈值确认, 避免长期超买时接飞刀)",
    )
    parser.add_argument(
        "--long-rsi-period", type=int, default=21,
        help="多周期模式的长周期 RSI 周期 (默认 21)",
    )
    parser.add_argument(
        "--long-rsi-threshold", type=float, default=50.0,
        help="多周期模式长周期 RSI 上限, 超过则不买 (默认 50)",
    )

    # === PE 选股策略参数 ===
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

    # === 动态波动率筛选参数 ===
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
    parser.add_argument(
        "--vol-mode", default="high", choices=["high", "low"],
        help="波动率筛选模式: high=选高波动(适合MA趋势), low=选低波动(适合RSI均值回归)",
    )

    # === 市场环境过滤参数 ===
    parser.add_argument(
        "--market-filter", type=str, default=None,
        choices=["price_above_ma", "ma_slope_up", "both"],
        help="市场环境过滤规则 (沪深300): price_above_ma=价格>MA60, "
             "ma_slope_up=MA60上行, both=两者同时满足",
    )

    # === 动态仓位管理参数 ===
    parser.add_argument(
        "--position-scaler", action="store_true",
        help="启用动态仓位管理 (基于沪深300 MA60 偏离度调整开仓资金比例)",
    )

    # === 多策略并行参数 ===
    parser.add_argument(
        "--rsi", action="store_true",
        help="启用 RSI 均值回归策略 (与 MA 趋势策略并行, 信号叠加)",
    )

    # === 组合级回撤止损参数 ===
    parser.add_argument(
        "--portfolio-dd", type=float, default=None,
        help="组合级回撤止损阈值 (如 0.12 = 从峰值回撤 12%% 清仓暂停), 不填=不启用",
    )

    return parser


def build_single_backtest_config(args) -> SingleBacktestConfig:
    """从 argparse Namespace 构建单股票回测配置"""
    return SingleBacktestConfig(
        ts_code=args.stock,
        start_date=args.start,
        end_date=args.end,
        short_window=args.short,
        long_window=args.long,
    )


def build_backtest_config(args) -> BacktestConfig:
    """从 argparse Namespace 构建组合回测配置"""
    return BacktestConfig(
        pool_name=args.pool,
        start_date=args.start,
        end_date=args.end,
        strategy_name=args.strategy,
        market_filter_rule=args.market_filter,
        use_position_scaler=args.position_scaler,
        use_rsi=args.rsi,
        ma=MAConfig(
            short_window=args.short,
            long_window=args.long,
            adx_threshold=args.adx_threshold,
        ),
        rsi=RSIConfig(
            rsi_period=args.rsi_period,
            oversold=args.oversold,
            overbought=args.overbought,
            adaptive=args.adaptive,
            lookback=args.rsi_lookback,
            low_q=args.low_q,
            high_q=args.high_q,
            vol_grouped=args.vol_grouped,
            vol_lookback=args.rsi_vol_lookback,
            vol_high=args.vol_high,
            vol_low=args.vol_low,
            multi_period=args.multi_period,
            long_rsi_period=args.long_rsi_period,
            long_rsi_threshold=args.long_rsi_threshold,
        ),
        vol_selector=VolSelectorConfig(
            dynamic_vol=args.dynamic_vol,
            vol_lookback=args.vol_lookback,
            vol_top=args.vol_top,
            vol_mode=args.vol_mode,
        ),
        risk=RiskConfig(
            stop_loss_type=args.stop_loss,
            stop_loss_pct=args.stop_pct,
            max_hold_days=args.max_hold_days,
            portfolio_dd_threshold=args.portfolio_dd,
        ),
    )


def build_pe_config(args) -> PEConfig:
    """从 argparse Namespace 构建 PE 选股回测配置"""
    return PEConfig(
        pool_name=args.pool,
        start_date=args.start,
        end_date=args.end,
        quantile_threshold=args.quantile,
        lookback_years=args.lookback,
        top_n=args.top_n,
        rebalance_freq=args.freq,
    )
