"""回测相关命令: 单股票回测、组合回测、PE选股回测"""
import os
import sys
import pandas as pd
from loguru import logger

from config.settings import TRAILING_STOP_PCT, STOP_LOSS_PCT
from simulation.account import VirtualAccount
from simulation.order_manager import OrderManager
from simulation.scheduler import SimulationScheduler
from monitor.reporter import ReportGenerator


def _print_summary(report_generator: ReportGenerator):
    """安全打印报告摘要 (处理 Windows 控制台编码)"""
    summary = report_generator.generate_text_summary()
    print(summary.encode(
        sys.stdout.encoding or "utf-8", errors="replace"
    ).decode(sys.stdout.encoding or "utf-8", errors="replace"))


def _get_output_dir() -> str:
    """获取回测输出目录 (output/), 不存在则创建"""
    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output")
    os.makedirs(output_dir, exist_ok=True)
    return output_dir


def _save_nav_and_trades(account: VirtualAccount, store, start_date: str, benchmark: bool = True):
    """保存净值CSV和交易明细CSV, 含沪深300基准对比"""
    output_dir = _get_output_dir()

    if account.daily_nav:
        nav_df = pd.DataFrame(account.daily_nav)

        if benchmark:
            benchmark_ts_code = "000300.SH"
            try:
                bench_df = store.load_index_daily(
                    ts_code=benchmark_ts_code, start=start_date
                )
                if not bench_df.empty:
                    bench_df = bench_df[["trade_date", "close"]].rename(
                        columns={"trade_date": "date", "close": "benchmark_close"}
                    )
                    nav_df = nav_df.merge(bench_df, on="date", how="left")
                    first_bench = nav_df["benchmark_close"].dropna().iloc[0]
                    nav_df["benchmark_nav"] = nav_df["benchmark_close"] / first_bench
                    nav_df["benchmark_nav"] = nav_df["benchmark_nav"].ffill().fillna(1.0)
                    nav_df["benchmark_return"] = nav_df["benchmark_nav"].pct_change(
                        fill_method=None
                    ).fillna(0)
                    nav_df["excess_return"] = nav_df["return"] - nav_df["benchmark_return"]
                    nav_df["excess_nav"] = (1 + nav_df["excess_return"]).cumprod() - 1
                    logger.info(f"基准对比: {benchmark_ts_code} 已对齐")
            except Exception as e:
                logger.warning(f"基准对比失败: {e}")

        nav_path = os.path.join(output_dir, "backtest_nav.csv")
        nav_df.to_csv(nav_path, index=False, encoding="utf-8-sig")
        logger.info(f"净值曲线已保存: {nav_path}")

    if account.trade_history:
        trades_df = pd.DataFrame(account.trade_history)
        trades_path = os.path.join(output_dir, "backtest_trades.csv")
        trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
        logger.info(f"交易明细已保存: {trades_path}")


def cmd_backtest(cfg):
    """
    单股票回测 (最小闭环版)

    流程: 数据库取日线 → MA策略生成信号 → VirtualAccount模拟 → 输出净值CSV

    Args:
        cfg: SingleBacktestConfig
    """
    from data.storage.database import DataStore
    from strategy.timing.ma_cross import MACrossStrategy

    end_label = cfg.end_date or "今"
    logger.info(f"=== 回测开始: {cfg.ts_code} ({cfg.start_date} ~ {end_label}) ===")
    logger.info(f"策略: MA({cfg.short_window},{cfg.long_window}) 双均线交叉")

    # 1. 加载数据
    store = DataStore()
    df = store.load_daily_price(ts_code=cfg.ts_code, start=cfg.start_date, end=cfg.end_date)
    if df.empty:
        logger.error(f"数据库无 {cfg.ts_code} 日线数据，请先拉取")
        return
    logger.info(f"加载数据: {len(df)} 行 ({df['trade_date'].min()} ~ {df['trade_date'].max()})")

    # 2. 生成信号
    strategy = MACrossStrategy(short_window=cfg.short_window, long_window=cfg.long_window)
    signals_df = strategy.generate_signals(df)

    signals_by_date = {}
    for _, row in signals_df.iterrows():
        if row["action"] in ("BUY", "SELL"):
            signals_by_date.setdefault(row["trade_date"], []).append({
                "ts_code": row["ts_code"],
                "action": row["action"],
                "price": float(row["close"]),
            })

    n_buy = sum(1 for s in signals_df["action"] if s == "BUY")
    n_sell = sum(1 for s in signals_df["action"] if s == "SELL")
    logger.info(f"信号: BUY={n_buy}, SELL={n_sell}")

    # 3. 跑模拟交易 (T日收盘生成信号 → T+1日开盘成交)
    account = VirtualAccount()
    om = OrderManager(account)
    scheduler = SimulationScheduler(account, om)

    trade_dates = sorted(df["trade_date"].unique())
    close_lookup = dict(zip(df["trade_date"], df["close"]))
    open_lookup = dict(zip(df["trade_date"], df["open"]))

    pending_signals = []

    for i, date in enumerate(trade_dates):
        exec_price = float(open_lookup.get(date, close_lookup[date]))
        close_price = float(close_lookup[date])
        prices = {cfg.ts_code: close_price}

        signals_to_execute = pending_signals
        pending_signals = []

        enriched = []
        for sig in signals_to_execute:
            if sig["action"] == "BUY":
                target_value = account.available_cash * 0.5
                volume = int(target_value / exec_price / 100) * 100
                if volume > 0:
                    sig["volume"] = volume
                    sig["price"] = exec_price
                    enriched.append(sig)
            else:
                sig["price"] = exec_price
                enriched.append(sig)

        scheduler.run_daily(date, enriched, prices)

        today_signals = signals_by_date.get(date, [])
        pending_signals.extend(today_signals)

    # 4. 输出结果
    output_dir = _get_output_dir()
    rg = ReportGenerator(account, output_dir=output_dir)
    _print_summary(rg)

    if account.daily_nav:
        nav_df = pd.DataFrame(account.daily_nav)

        # 买入持有基准 (单股票回测最合理的基准)
        stock_bench = df[["trade_date", "close"]].rename(
            columns={"trade_date": "date", "close": "buyhold_close"}
        )
        nav_df = nav_df.merge(stock_bench, on="date", how="left")
        first_close = nav_df["buyhold_close"].iloc[0]
        nav_df["buyhold_nav"] = nav_df["buyhold_close"] / first_close
        nav_df["buyhold_return"] = nav_df["buyhold_nav"].pct_change(fill_method=None).fillna(0)
        nav_df["buyhold_excess"] = nav_df["return"] - nav_df["buyhold_return"]

        # 沪深300基准
        benchmark_ts_code = "000300.SH"
        try:
            bench_df = store.load_index_daily(
                ts_code=benchmark_ts_code,
                start=cfg.start_date,
                end=cfg.end_date,
            )
            if not bench_df.empty:
                bench_df = bench_df[["trade_date", "close"]].rename(
                    columns={"trade_date": "date", "close": "benchmark_close"}
                )
                nav_df = nav_df.merge(bench_df, on="date", how="left")
                first_bench = nav_df["benchmark_close"].dropna().iloc[0]
                nav_df["benchmark_nav"] = nav_df["benchmark_close"] / first_bench
                nav_df["benchmark_nav"] = nav_df["benchmark_nav"].ffill().fillna(1.0)
                nav_df["benchmark_return"] = nav_df["benchmark_nav"].pct_change(fill_method=None).fillna(0)
                nav_df["excess_return"] = nav_df["return"] - nav_df["benchmark_return"]
                nav_df["excess_nav"] = (1 + nav_df["excess_return"]).cumprod() - 1
                logger.info(f"基准对比: {benchmark_ts_code} 数据 {len(bench_df)} 行已对齐")
            else:
                logger.warning(f"沪深300数据为空, 跳过市场基准对比")
        except Exception as e:
            logger.warning(f"基准对比失败: {e}")

        nav_path = os.path.join(output_dir, "backtest_nav.csv")
        nav_df.to_csv(nav_path, index=False, encoding="utf-8-sig")
        logger.info(f"净值曲线已保存: {nav_path}")

    if account.trade_history:
        trades_df = pd.DataFrame(account.trade_history)
        trades_path = os.path.join(output_dir, "backtest_trades.csv")
        trades_df.to_csv(trades_path, index=False, encoding="utf-8-sig")
        logger.info(f"交易明细已保存: {trades_path}")

    logger.info(f"=== 回测完成: 累计收益率 {account.total_return:.2%} ===")


def cmd_backtest_pool(cfg):
    """多股票组合回测

    Args:
        cfg: BacktestConfig (含 ma/rsi/vol_selector/risk 子配置)
    """
    from config.stock_pool_loader import load_pool
    from data.storage.database import DataStore
    from strategy.portfolio_runner import PortfolioRunner
    from cli.data_commands import _ensure_pool_data

    pool = load_pool(cfg.pool_name)
    logger.info(f"=== 组合回测开始: 池 [{cfg.pool_name}] ({len(pool['stocks'])} 只股票) ===")
    _log_strategy_info(cfg)
    logger.info(f"资金分配: 按信号动态均分 (总预算 90%), 单股权重上限")
    if cfg.vol_selector.dynamic_vol:
        mode_label = "高波动" if cfg.vol_selector.vol_mode == "high" else "低波动"
        logger.info(f"动态波动率筛选 ({mode_label}模式): 回看 {cfg.vol_selector.vol_lookback} 天, 选前 {cfg.vol_selector.vol_top} 只, 月度调仓")

    # 止损
    stop_loss = _build_stop_loss(cfg.risk)

    # 1. 加载数据
    store = DataStore()
    strategy = _build_strategy(cfg)
    account = VirtualAccount()
    om = OrderManager(account)
    scheduler = SimulationScheduler(account, om)

    # 动态波动率筛选器
    vol_selector = None
    if cfg.vol_selector.dynamic_vol:
        from strategy.select_stock.volatility_selector import VolatilitySelector
        vol_selector = VolatilitySelector(
            lookback_days=cfg.vol_selector.vol_lookback,
            top_n=cfg.vol_selector.vol_top,
            rebalance_freq="monthly",
            mode=cfg.vol_selector.vol_mode,
        )

    # 市场环境过滤器
    market_filter = None
    if cfg.market_filter_rule:
        from strategy.risk.market_filter import MarketFilter
        market_filter = MarketFilter(store, rule=cfg.market_filter_rule, ma_period=60)
        logger.info(f"市场环境过滤: {cfg.market_filter_rule}")

    # 动态仓位管理器
    position_scaler = None
    if cfg.use_position_scaler:
        from strategy.risk.position_scaler import PositionScaler
        position_scaler = PositionScaler(store, ma_period=60)
        logger.info(f"动态仓位管理: 启用 (基于沪深300 MA60)")

    # 附加策略 (多策略并行)
    extra_strategies = []
    if cfg.use_rsi:
        from strategy.timing.rsi_revert import RSIRevertStrategy
        rsi_strategy = RSIRevertStrategy(rsi_period=14, oversold=30, overbought=70)
        extra_strategies.append(rsi_strategy)
        logger.info(f"附加策略: RSI 均值回归 (period=14, oversold=30, overbought=70)")

    # 组合级回撤止损
    portfolio_stop = None
    if cfg.risk.portfolio_dd_threshold:
        from strategy.risk.portfolio_stop import PortfolioDrawdownStop
        portfolio_stop = PortfolioDrawdownStop(
            drawdown_threshold=cfg.risk.portfolio_dd_threshold,
            recovery_days=20,
        )
        logger.info(f"组合回撤止损: 阈值 {cfg.risk.portfolio_dd_threshold:.0%}, 暂停 20 个交易日")

    runner = PortfolioRunner(
        pool, strategy, account, scheduler,
        stop_loss=stop_loss, vol_selector=vol_selector,
        market_filter=market_filter,
        position_scaler=position_scaler,
        extra_strategies=extra_strategies,
        portfolio_stop=portfolio_stop,
    )
    _ensure_pool_data(store, pool, cfg.start_date, cfg.end_date)
    runner.load_data(store, cfg.start_date, cfg.end_date)

    if len(runner.stock_data) == 0:
        logger.error("无可用数据, 终止回测")
        return

    # 2. 生成所有股票的信号
    runner.generate_all_signals()

    # 3. 执行回测
    runner.run_backtest()

    # 4. 输出结果
    output_dir = _get_output_dir()
    rg = ReportGenerator(account, output_dir=output_dir)
    _print_summary(rg)

    _save_nav_and_trades(account, store, cfg.start_date, benchmark=True)

    logger.info(f"=== 组合回测完成: 累计收益率 {account.total_return:.2%} ===")


def _log_strategy_info(cfg):
    """打印策略配置日志"""
    if cfg.strategy_name == "rsi":
        r = cfg.rsi
        if r.multi_period:
            logger.info(f"策略: RSI 均值回归 (多周期共振, period={r.rsi_period}, long_period={r.long_rsi_period}, long_thr={r.long_rsi_threshold})")
        elif r.vol_grouped:
            logger.info(f"策略: RSI 均值回归 (波动率分组模式, period={r.rsi_period}, vol_lookback={r.vol_lookback}, 高>{r.vol_high}用20/80, 中{r.vol_low}~{r.vol_high}用30/70, 低<{r.vol_low}跳过)")
        elif r.adaptive:
            logger.info(f"策略: RSI 均值回归 (自适应模式, period={r.rsi_period}, lookback={r.lookback}, q=[{r.low_q},{r.high_q}])")
        else:
            logger.info(f"策略: RSI 均值回归 (固定阈值, period={r.rsi_period}, oversold={r.oversold}, overbought={r.overbought})")
    else:
        logger.info(f"策略: MA({cfg.ma.short_window},{cfg.ma.long_window}) 双均线交叉")


def _build_stop_loss(risk_cfg):
    """根据风控配置构建止损对象"""
    from strategy.risk.stop_loss import TrailingStopLoss, FixedStopLoss, TimeStopLoss, ComboStopLoss
    stop_loss = None
    if risk_cfg.stop_loss_type == "trailing":
        pct = risk_cfg.stop_loss_pct if risk_cfg.stop_loss_pct else TRAILING_STOP_PCT
        stop_loss = TrailingStopLoss(trailing_pct=pct)
        logger.info(f"止损: 追踪止损 (从最高价回撤 {pct:.0%})")
    elif risk_cfg.stop_loss_type == "fixed":
        pct = risk_cfg.stop_loss_pct if risk_cfg.stop_loss_pct else STOP_LOSS_PCT
        stop_loss = FixedStopLoss(stop_loss_pct=pct)
        logger.info(f"止损: 固定止损 (亏损 {pct:.0%})")
    elif risk_cfg.stop_loss_type == "time":
        max_days = risk_cfg.max_hold_days
        stop_loss = TimeStopLoss(max_hold_days=max_days)
        logger.info(f"止损: 时间止损 (持有 {max_days} 交易日无盈利则卖)")
    elif risk_cfg.stop_loss_type == "combo":
        pct = risk_cfg.stop_loss_pct if risk_cfg.stop_loss_pct else TRAILING_STOP_PCT
        max_days = risk_cfg.max_hold_days
        stop_loss = ComboStopLoss(trailing_pct=pct, max_hold_days=max_days)
        logger.info(f"止损: 组合止损 (追踪{pct:.0%}或持有{max_days}天, 先到先卖)")
    elif risk_cfg.stop_loss_type == "none":
        logger.info("止损: 已禁用")
    return stop_loss


def _build_strategy(cfg):
    """根据配置构建策略对象"""
    if cfg.strategy_name == "rsi":
        from strategy.timing.rsi_revert import RSIRevertStrategy
        r = cfg.rsi
        return RSIRevertStrategy(
            rsi_period=r.rsi_period,
            oversold=r.oversold,
            overbought=r.overbought,
            adaptive=r.adaptive,
            lookback=r.lookback,
            low_q=r.low_q,
            high_q=r.high_q,
            vol_grouped=r.vol_grouped,
            vol_lookback=r.vol_lookback,
            vol_high=r.vol_high,
            vol_low=r.vol_low,
            multi_period=r.multi_period,
            long_rsi_period=r.long_rsi_period,
            long_rsi_threshold=r.long_rsi_threshold,
        )
    else:
        from strategy.timing.ma_cross import MACrossStrategy
        return MACrossStrategy(
            short_window=cfg.ma.short_window,
            long_window=cfg.ma.long_window,
            adx_threshold=cfg.ma.adx_threshold,
        )


def cmd_backtest_pe(cfg):
    """PE 分位数选股策略回测

    Args:
        cfg: PEConfig
    """
    from config.stock_pool_loader import load_pool
    from data.storage.database import DataStore
    from strategy.select_stock.pe_quantile import PEQuantileStrategy
    from strategy.select_stock_runner import SelectionRunner

    pool = load_pool(cfg.pool_name)
    candidate_pool = [s["ts_code"] for s in pool["stocks"]]

    logger.info(f"=== PE 选股回测开始: 池 [{cfg.pool_name}] ({len(candidate_pool)} 只候选) ===")
    logger.info(
        f"策略: PE 历史分位数 (阈值 {cfg.quantile_threshold:.0%}, "
        f"回看 {cfg.lookback_years} 年, 持有 {cfg.top_n} 只, {cfg.rebalance_freq} 调仓)"
    )

    # 1. 初始化
    store = DataStore()
    strategy = PEQuantileStrategy(
        quantile_threshold=cfg.quantile_threshold,
        lookback_years=cfg.lookback_years,
        top_n=cfg.top_n,
        rebalance_freq=cfg.rebalance_freq,
    )
    account = VirtualAccount()
    om = OrderManager(account)
    scheduler = SimulationScheduler(account, om)

    runner = SelectionRunner(strategy, account, scheduler, candidate_pool)
    runner.load_data(store, cfg.start_date, cfg.end_date)

    if not runner.stock_data:
        logger.error("无可用日线数据, 终止回测")
        return
    if not runner.pe_data:
        logger.error("无可用 PE 数据, 请先运行: python data/fetcher/fetch_pe_data.py --pool default")
        return

    # 2. 执行回测
    runner.run_backtest()

    # 3. 输出结果
    output_dir = _get_output_dir()
    rg = ReportGenerator(account, output_dir=output_dir)
    _print_summary(rg)

    # 打印调仓历史
    if runner.rebalance_log:
        print("\n" + "=" * 60)
        print("调仓历史")
        print("=" * 60)
        for log in runner.rebalance_log:
            print(f"  {log['date']}: 目标 {log['target']}, 信号 {log['signals']} 个")

    _save_nav_and_trades(account, store, cfg.start_date, benchmark=True)

    logger.info(f"=== PE 选股回测完成: 累计收益率 {account.total_return:.2%} ===")
