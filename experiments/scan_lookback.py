"""
扫描事前波动率筛选的回看窗口参数

对比 30/60/90/120 天回看窗口对 MA(5,30) 策略的影响
统一配置: csi100 池 + MA(5,30) + 8%追踪止损 + 选前10只 + 月度调仓

用法:
    python tests/scan_lookback.py
"""
import os
import sys
import json
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.stock_pool_loader import load_pool
from config.settings import TRAILING_STOP_PCT
from data.storage.database import DataStore
from data.storage.models import init_database
from simulation.account import VirtualAccount
from simulation.order_manager import OrderManager
from simulation.scheduler import SimulationScheduler
from strategy.timing.ma_cross import MACrossStrategy
from strategy.portfolio_runner import PortfolioRunner
from strategy.risk.stop_loss import TrailingStopLoss
from strategy.select_stock.volatility_selector import VolatilitySelector


def run_single(lookback_days: int, top_n: int = 10) -> dict:
    """跑单组参数, 返回关键指标"""
    print(f"\n{'='*60}")
    print(f"回看窗口 = {lookback_days} 天")
    print(f"{'='*60}")

    pool = load_pool("csi100")
    strategy = MACrossStrategy(short_window=5, long_window=30)
    account = VirtualAccount()
    om = OrderManager(account)
    scheduler = SimulationScheduler(account, om)
    stop_loss = TrailingStopLoss(trailing_pct=TRAILING_STOP_PCT)

    vol_selector = VolatilitySelector(
        lookback_days=lookback_days,
        top_n=top_n,
        rebalance_freq="monthly",
    )

    runner = PortfolioRunner(
        pool, strategy, account, scheduler,
        stop_loss=stop_loss, vol_selector=vol_selector,
    )

    store = DataStore()
    runner.load_data(store, "20240101")
    if len(runner.stock_data) == 0:
        return {"lookback": lookback_days, "error": "无数据"}

    runner.generate_all_signals()
    runner.run_backtest()

    # 计算指标
    total_asset = account.total_asset
    total_return = account.total_return
    initial = 1_000_000

    # 从净值 CSV 读取更详细指标
    nav_df = pd.DataFrame(account.daily_nav)
    if nav_df.empty:
        return {"lookback": lookback_days, "return": total_return}

    # 基准
    try:
        bench_df = store.load_index_daily(ts_code="000300.SH", start="20240101")
        bench_df = bench_df[["trade_date", "close"]].rename(
            columns={"trade_date": "date", "close": "bench_close"}
        )
        nav_df = nav_df.merge(bench_df, on="date", how="left")
        first_bench = nav_df["bench_close"].dropna().iloc[0]
        nav_df["bench_nav"] = nav_df["bench_close"] / first_bench
        nav_df["bench_nav"] = nav_df["bench_nav"].ffill().fillna(1.0)
        bench_return = nav_df["bench_nav"].iloc[-1] - 1
    except Exception:
        bench_return = 0.4376  # 沪深300 区间收益

    # 最大回撤
    nav_series = nav_df["nav"].astype(float)
    peak = nav_series.cummax()
    drawdown = (nav_series - peak) / peak
    max_dd = drawdown.min()

    # 年化波动 (日收益率标准差 × sqrt(244))
    daily_ret = nav_df["return"].astype(float)
    ann_vol = daily_ret.std() * (244 ** 0.5)

    # 夏普 (无风险利率=0)
    ann_ret = (1 + total_return) ** (244 / len(nav_df)) - 1
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # IR
    excess_ret = nav_df["return"].astype(float) - nav_df["bench_nav"].pct_change().fillna(0).astype(float)
    tracking_err = excess_ret.std() * (244 ** 0.5)
    ir = (ann_ret - ((1 + bench_return) ** (244 / len(nav_df)) - 1)) / tracking_err if tracking_err > 0 else 0

    # 交易统计
    trades = account.trade_history
    n_buys = sum(1 for t in trades if t["direction"] == "BUY")
    n_sells = sum(1 for t in trades if t["direction"] == "SELL")
    pnls = [t.get("pnl") for t in trades if t.get("pnl") is not None and not pd.isna(t.get("pnl"))]
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]
    win_rate = len(wins) / len(pnls) if pnls else 0
    avg_win = sum(wins) / len(wins) if wins else 0
    avg_loss = sum(losses) / len(losses) if losses else 0
    profit_loss_ratio = abs(avg_win / avg_loss) if avg_loss != 0 else 0

    result = {
        "lookback": lookback_days,
        "cumulative_return": total_return,
        "annualized_return": ann_ret,
        "max_drawdown": max_dd,
        "annualized_volatility": ann_vol,
        "sharpe": sharpe,
        "ir": ir,
        "benchmark_return": bench_return,
        "excess_return": total_return - bench_return,
        "win_rate": win_rate,
        "profit_loss_ratio": profit_loss_ratio,
        "n_trades": n_buys + n_sells,
        "n_buys": n_buys,
        "n_sells": n_sells,
    }

    print(f"\n--- 回看 {lookback_days} 天 结果 ---")
    print(f"累计收益: {total_return:.2%}")
    print(f"最大回撤: {max_dd:.2%}")
    print(f"夏普: {sharpe:.3f}")
    print(f"IR: {ir:.3f}")
    print(f"超额: {total_return - bench_return:.2%}")

    return result


def main():
    # 初始化数据库
    init_database()

    lookbacks = [30, 60, 90, 120]
    results = []
    for lb in lookbacks:
        try:
            r = run_single(lb)
            results.append(r)
        except Exception as e:
            print(f"回看 {lb} 天失败: {e}")
            import traceback
            traceback.print_exc()
            results.append({"lookback": lb, "error": str(e)})

    # 汇总对比表
    print("\n" + "=" * 80)
    print("回看窗口扫描汇总")
    print("=" * 80)
    print(f"{'回看天数':<10}{'累计收益':<12}{'年化收益':<12}{'最大回撤':<12}{'年化波动':<12}{'夏普':<8}{'IR':<8}{'超额':<12}{'胜率':<8}{'盈亏比':<8}{'交易笔数':<10}")
    print("-" * 110)
    for r in results:
        if "error" in r:
            print(f"{r['lookback']:<10}ERROR: {r['error']}")
            continue
        print(
            f"{r['lookback']:<10}"
            f"{r['cumulative_return']:<12.2%}"
            f"{r['annualized_return']:<12.2%}"
            f"{r['max_drawdown']:<12.2%}"
            f"{r['annualized_volatility']:<12.2%}"
            f"{r['sharpe']:<8.3f}"
            f"{r['ir']:<8.3f}"
            f"{r['excess_return']:<12.2%}"
            f"{r['win_rate']:<8.2%}"
            f"{r['profit_loss_ratio']:<8.2f}"
            f"{r['n_trades']:<10}"
        )

    # 保存结果到 JSON
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output", "scan_lookback_results.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
