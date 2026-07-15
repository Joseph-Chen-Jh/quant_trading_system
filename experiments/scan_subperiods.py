"""
回看窗口的子区间稳定性验证

把 2024-01-02 ~ 2026-07-09 拆成 5 个半年子区间,
每个子区间独立跑 MA(5,30) + 8%止损 + csi100池 + 回看N天 + 选前10只,
看指定回看窗口在每段是否都稳定跑赢基准。

说明:
    - 每段需要前 N 天作为波动率预热期 (只算波动率, 不计绩效)
    - 所以每段的 "数据起始日" 比 "绩效起始日" 早 N 个交易日
    - 为简化, 数据统一从 2023-07-01 拉取 (保证第一段有预热数据)
    - 但绩效只统计每段区间内

用法:
    python tests/scan_subperiods.py              # 默认 120 天
    python tests/scan_subperiods.py 60           # 指定 60 天
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


# 5 个子区间 (2.5年: 2024-01 ~ 2026-07)
SUBPERIODS_5 = [
    ("2024-01-02", "2024-06-28", "2024H1"),
    ("2024-07-01", "2024-12-31", "2024H2"),
    ("2025-01-01", "2025-06-30", "2025H1"),
    ("2025-07-01", "2025-12-31", "2025H2"),
    ("2026-01-01", "2026-07-09", "2026H1"),
]

# 10 个子区间 (5年: 2021-07 ~ 2026-07)
SUBPERIODS_10 = [
    ("2021-07-01", "2021-12-31", "2021H2"),
    ("2022-01-01", "2022-06-30", "2022H1"),
    ("2022-07-01", "2022-12-30", "2022H2"),
    ("2023-01-01", "2023-06-30", "2023H1"),
    ("2023-07-01", "2023-12-29", "2023H2"),
    ("2024-01-02", "2024-06-28", "2024H1"),
    ("2024-07-01", "2024-12-31", "2024H2"),
    ("2025-01-01", "2025-06-30", "2025H1"),
    ("2025-07-01", "2025-12-31", "2025H2"),
    ("2026-01-01", "2026-07-09", "2026H1"),
]

# 默认 5 段 (2.5年), --5y 切换到 10 段 (5年)
SUBPERIODS = SUBPERIODS_5

# 数据起始日: 5年模式用 20210101 (留半年给MA30/波动率预热), 2.5年模式用 20240101
DATA_START = "20240101"


def run_subperiod(start_date: str, end_date: str, label: str, lookback_days: int, use_scaler: bool = False, use_rsi: bool = False, pool_name: str = "csi100") -> dict:
    """跑单个子区间, 返回关键指标"""
    start_yyyymmdd = start_date.replace("-", "")
    end_yyyymmdd = end_date.replace("-", "")

    print(f"\n{'='*60}")
    print(f"子区间: {label} ({start_date} ~ {end_date}) [回看 {lookback_days} 天, 仓位管理={use_scaler}, RSI={use_rsi}, 池={pool_name}]")
    print(f"{'='*60}")

    pool = load_pool(pool_name)
    strategy = MACrossStrategy(short_window=5, long_window=30)
    account = VirtualAccount()
    om = OrderManager(account)
    scheduler = SimulationScheduler(account, om)
    stop_loss = TrailingStopLoss(trailing_pct=TRAILING_STOP_PCT)

    vol_selector = VolatilitySelector(
        lookback_days=lookback_days,
        top_n=10,
        rebalance_freq="monthly",
    )

    store = DataStore()

    position_scaler = None
    if use_scaler:
        from strategy.risk.position_scaler import PositionScaler
        position_scaler = PositionScaler(store, ma_period=60)

    extra_strategies = []
    if use_rsi:
        from strategy.timing.rsi_revert import RSIRevertStrategy
        extra_strategies.append(RSIRevertStrategy(rsi_period=14, oversold=30, overbought=70))

    runner = PortfolioRunner(
        pool, strategy, account, scheduler,
        stop_loss=stop_loss, vol_selector=vol_selector,
        position_scaler=position_scaler,
        extra_strategies=extra_strategies,
    )

    # 每个子区间独立回测: 数据从 (子区间起始日 - lookback_days) 开始加载
    # 预留 lookback_days 作为波动率预热期 (只算波动率, 不计绩效)
    # 这样 run_backtest 只跑 [预热期, 子区间结束] 这段, 账户初始资金为 100 万
    import datetime as _dt
    start_dt = _dt.datetime.strptime(start_date, "%Y-%m-%d")
    # 预热期: lookback_days 个交易日 ≈ lookback_days * 1.5 个自然日, 多留一些余量
    warmup_days = int(lookback_days * 1.6) + 30
    data_start_dt = start_dt - _dt.timedelta(days=warmup_days)
    data_start = data_start_dt.strftime("%Y%m%d")

    runner.load_data(store, data_start)
    if len(runner.stock_data) == 0:
        return {"label": label, "error": "无数据"}

    runner.generate_all_signals()
    # trade_start_date = 子区间起始日, 之前为预热期 (只更新波动率池, 不交易)
    runner.run_backtest(trade_start_date=start_yyyymmdd)

    # 从全量净值中切片统计 [start, end]
    nav_df = pd.DataFrame(account.daily_nav)
    if nav_df.empty:
        return {"label": label, "error": "无净值数据"}

    nav_df["date_dt"] = pd.to_datetime(nav_df["date"], format="%Y%m%d")
    mask = (nav_df["date_dt"] >= pd.to_datetime(start_date)) & (
        nav_df["date_dt"] <= pd.to_datetime(end_date)
    )
    sub_nav = nav_df[mask].copy()

    if len(sub_nav) < 10:
        return {"label": label, "error": f"子区间净值记录过少 ({len(sub_nav)} 行)"}

    # 区间内绩效: 用区间首日净值作为基准, 归一化
    initial_nav = sub_nav["nav"].iloc[0]
    sub_nav["sub_return"] = sub_nav["nav"].astype(float) / initial_nav - 1
    total_return = sub_nav["sub_return"].iloc[-1]

    # 区间内基准
    try:
        bench_df = store.load_index_daily(ts_code="000300.SH", start=data_start)
        bench_df["date_dt"] = pd.to_datetime(bench_df["trade_date"], format="%Y%m%d")
        bench_mask = (bench_df["date_dt"] >= pd.to_datetime(start_date)) & (
            bench_df["date_dt"] <= pd.to_datetime(end_date)
        )
        sub_bench = bench_df[bench_mask].copy()
        if not sub_bench.empty:
            first_bench = sub_bench["close"].iloc[0]
            bench_return = sub_bench["close"].iloc[-1] / first_bench - 1
        else:
            bench_return = 0.0
    except Exception:
        bench_return = 0.0

    # 区间内最大回撤
    nav_series = sub_nav["nav"].astype(float)
    peak = nav_series.cummax()
    drawdown = (nav_series - peak) / peak
    max_dd = drawdown.min()

    # 区间内年化波动
    daily_ret = sub_nav["return"].astype(float)
    ann_vol = daily_ret.std() * (244 ** 0.5)

    # 年化收益 (按区间天数)
    n_days = len(sub_nav)
    ann_ret = (1 + total_return) ** (244 / n_days) - 1 if total_return > -1 else -1

    # 夏普
    sharpe = ann_ret / ann_vol if ann_vol > 0 else 0

    # 交易统计 (区间内)
    trades = account.trade_history
    n_buys = sum(
        1 for t in trades
        if t["direction"] == "BUY" and start_yyyymmdd <= str(t["trade_date"]) <= end_yyyymmdd
    )
    n_sells = sum(
        1 for t in trades
        if t["direction"] == "SELL" and start_yyyymmdd <= str(t["trade_date"]) <= end_yyyymmdd
    )

    result = {
        "label": label,
        "start": start_date,
        "end": end_date,
        "n_days": n_days,
        "cumulative_return": total_return,
        "annualized_return": ann_ret,
        "max_drawdown": max_dd,
        "annualized_volatility": ann_vol,
        "sharpe": sharpe,
        "benchmark_return": bench_return,
        "excess_return": total_return - bench_return,
        "n_buys": n_buys,
        "n_sells": n_sells,
    }

    print(f"\n--- {label} 结果 ---")
    print(f"交易日: {n_days}")
    print(f"累计收益: {total_return:.2%}")
    print(f"沪深300: {bench_return:.2%}")
    print(f"超额: {total_return - bench_return:.2%}")
    print(f"最大回撤: {max_dd:.2%}")
    print(f"夏普: {sharpe:.3f}")

    return result


def main():
    lookback_days = int(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("--") else 120
    use_scaler = "--scaler" in sys.argv
    use_rsi = "--rsi" in sys.argv
    use_5y = "--5y" in sys.argv
    # 解析 --pool 参数
    pool_name = "csi300"
    for i, arg in enumerate(sys.argv):
        if arg == "--pool" and i + 1 < len(sys.argv):
            pool_name = sys.argv[i + 1]

    # 切换到 5 年模式 (10 段子区间)
    global SUBPERIODS
    if use_5y:
        SUBPERIODS = SUBPERIODS_10

    mode_label = "5年(10段)" if use_5y else "2.5年(5段)"
    print(f"=== 回看窗口 {lookback_days} 天 子区间稳定性验证 [{mode_label}] (仓位管理={use_scaler}, RSI={use_rsi}, 池={pool_name}) ===")

    init_database()

    results = []
    for start, end, label in SUBPERIODS:
        try:
            r = run_subperiod(start, end, label, lookback_days, use_scaler=use_scaler, use_rsi=use_rsi, pool_name=pool_name)
            results.append(r)
        except Exception as e:
            print(f"{label} 失败: {e}")
            import traceback
            traceback.print_exc()
            results.append({"label": label, "error": str(e)})

    # 汇总
    print("\n" + "=" * 100)
    suffix = " + 仓位管理" if use_scaler else ""
    suffix += " + RSI" if use_rsi else ""
    print(f"{lookback_days}天回看窗口{suffix} — 子区间稳定性验证")
    print("=" * 100)
    header = (
        f"{'区间':<12}{'交易日':<8}{'累计收益':<12}{'年化收益':<12}"
        f"{'沪深300':<10}{'超额':<12}{'最大回撤':<12}{'年化波动':<12}"
        f"{'夏普':<8}{'买入':<6}{'卖出':<6}"
    )
    print(header)
    print("-" * 110)
    for r in results:
        if "error" in r:
            print(f"{r['label']:<12}ERROR: {r['error']}")
            continue
        print(
            f"{r['label']:<12}"
            f"{r['n_days']:<8}"
            f"{r['cumulative_return']:<12.2%}"
            f"{r['annualized_return']:<12.2%}"
            f"{r['benchmark_return']:<10.2%}"
            f"{r['excess_return']:<12.2%}"
            f"{r['max_drawdown']:<12.2%}"
            f"{r['annualized_volatility']:<12.2%}"
            f"{r['sharpe']:<8.3f}"
            f"{r['n_buys']:<6}"
            f"{r['n_sells']:<6}"
        )

    # 汇总统计
    valid = [r for r in results if "error" not in r]
    if valid:
        excess_returns = [r["excess_return"] for r in valid]
        sharpes = [r["sharpe"] for r in valid]
        n_positive_excess = sum(1 for e in excess_returns if e > 0)
        print(f"\n--- 汇总 ---")
        print(f"子区间数: {len(valid)}")
        print(f"超额收益为正的区间数: {n_positive_excess}/{len(valid)}")
        print(f"超额收益均值: {sum(excess_returns)/len(excess_returns):.2%}")
        print(f"超额收益范围: {min(excess_returns):.2%} ~ {max(excess_returns):.2%}")
        print(f"夏普均值: {sum(sharpes)/len(sharpes):.3f}")
        print(f"夏普范围: {min(sharpes):.3f} ~ {max(sharpes):.3f}")

    suffix_str = "_scaler" if use_scaler else ""
    suffix_str += "_rsi" if use_rsi else ""
    suffix_str += f"_{pool_name}" if pool_name != "csi100" else ""
    suffix_str += "_5y" if use_5y else ""
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output", f"scan_subperiods_{lookback_days}d{suffix_str}_results.json"
    )
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n结果已保存: {out_path}")


if __name__ == "__main__":
    main()
