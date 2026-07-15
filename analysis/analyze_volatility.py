"""
股票波动率与盈亏贡献分析

目的:
    从 backtest_trades.csv 提取每只股票的盈亏贡献,
    结合日线数据计算波动率, 验证"高波动股是否贡献正收益".
    模拟筛选: 如果只交易波动率前 N 只, 收益会变成多少.

用法:
    python tests/analyze_volatility.py
    python tests/analyze_volatility.py --pool pe_universe
"""
import os
import sys
import argparse
from pathlib import Path

# 确保项目根目录在 path 中
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd
import numpy as np
from loguru import logger

from config.stock_pool_loader import load_pool
from data.storage.database import DataStore


def load_trades():
    """加载交易明细"""
    path = PROJECT_ROOT / "backtest_trades.csv"
    if not path.exists():
        logger.error(f"未找到交易明细: {path}")
        sys.exit(1)
    df = pd.read_csv(path)
    logger.info(f"加载交易明细: {len(df)} 行")
    return df


def load_daily_prices(ts_codes):
    """从 SQLite 加载日线数据"""
    store = DataStore()
    all_data = {}
    for ts_code in ts_codes:
        df = store.load_daily_price(ts_code)
        if not df.empty:
            df["trade_date"] = df["trade_date"].astype(str)
            df = df.sort_values("trade_date").reset_index(drop=True)
            all_data[ts_code] = df
    logger.info(f"加载日线数据: {len(all_data)}/{len(ts_codes)} 只股票")
    return all_data


def compute_volatility(daily_data, start_date="20240101"):
    """计算每只股票的日均波动率 (收益率标准差 × sqrt(244))"""
    vol_stats = {}
    for ts_code, df in daily_data.items():
        df = df[df["trade_date"] >= start_date].copy()
        if len(df) < 20:
            continue
        # 日收益率
        df["ret"] = df["close"].pct_change()
        daily_vol = df["ret"].std()
        ann_vol = daily_vol * (244 ** 0.5)
        # ATR (Average True Range) 占价比
        df["tr"] = np.maximum(
            df["high"] - df["low"],
            np.maximum(
                abs(df["high"] - df["close"].shift(1)),
                abs(df["low"] - df["close"].shift(1)),
            ),
        )
        atr_pct = (df["tr"].rolling(20).mean() / df["close"]).mean()
        vol_stats[ts_code] = {
            "daily_vol": daily_vol,
            "ann_vol": ann_vol,
            "atr_pct": atr_pct,
            "n_days": len(df),
            "avg_close": df["close"].mean(),
        }
    return vol_stats


def compute_pnl_by_stock(trades):
    """按股票统计盈亏"""
    sells = trades[trades["direction"] == "SELL"].copy()
    stats = {}
    for ts_code, group in sells.groupby("ts_code"):
        wins = (group["pnl"] > 0).sum()
        losses = (group["pnl"] <= 0).sum()
        total_closed = wins + losses
        stats[ts_code] = {
            "total_pnl": group["pnl"].sum(),
            "n_trades": total_closed,
            "n_wins": wins,
            "n_losses": losses,
            "win_rate": wins / total_closed if total_closed > 0 else 0,
            "avg_pnl": group["pnl"].mean(),
            "max_win": group["pnl"].max(),
            "max_loss": group["pnl"].min(),
        }
    return stats


def analyze(trades, daily_data, start_date="20240101"):
    """主分析: 合并波动率与盈亏"""
    vol_stats = compute_volatility(daily_data, start_date)
    pnl_stats = compute_pnl_by_stock(trades)

    # 合并成一张表
    rows = []
    all_codes = set(vol_stats.keys()) | set(pnl_stats.keys())
    for ts_code in all_codes:
        v = vol_stats.get(ts_code, {})
        p = pnl_stats.get(ts_code, {})
        rows.append({
            "ts_code": ts_code,
            "ann_vol": v.get("ann_vol", np.nan),
            "atr_pct": v.get("atr_pct", np.nan),
            "avg_close": v.get("avg_close", np.nan),
            "total_pnl": p.get("total_pnl", 0),
            "n_trades": p.get("n_trades", 0),
            "win_rate": p.get("win_rate", 0),
            "avg_pnl": p.get("avg_pnl", 0),
            "max_win": p.get("max_win", 0),
            "max_loss": p.get("max_loss", 0),
        })

    df = pd.DataFrame(rows)
    df = df.sort_values("ann_vol", ascending=False).reset_index(drop=True)
    return df


def print_section(title):
    print("\n" + "=" * 70)
    print(f"  {title}")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pool", default="pe_universe", help="股票池名称")
    parser.add_argument("--start", default="20240101", help="分析起始日期")
    args = parser.parse_args()

    print_section("股票波动率与盈亏贡献分析")

    # 1. 加载数据
    pool = load_pool(args.pool)
    ts_codes = [s["ts_code"] for s in pool["stocks"]]
    print(f"\n股票池: {args.pool} ({len(ts_codes)} 只)")
    print(f"分析区间: {args.start} ~ 至今")

    trades = load_trades()
    daily_data = load_daily_prices(ts_codes)

    # 2. 分析
    df = analyze(trades, daily_data, args.start)

    # 3. 输出完整排序表
    print_section("按波动率排序的股票表现")
    print(f"\n{'ts_code':<14} {'年化波动':>8} {'ATR%':>7} {'总盈亏':>12} {'交易数':>6} {'胜率':>7} {'平均盈亏':>10}")
    print("-" * 75)
    for _, row in df.iterrows():
        print(
            f"{row['ts_code']:<14} "
            f"{row['ann_vol']:>7.1%} "
            f"{row['atr_pct']:>6.1%} "
            f"{row['total_pnl']:>12,.0f} "
            f"{row['n_trades']:>6} "
            f"{row['win_rate']:>6.1%} "
            f"{row['avg_pnl']:>10,.0f}"
        )

    # 4. 高波动 vs 低波动对比
    print_section("高波动 vs 低波动 分组对比")
    df_valid = df.dropna(subset=["ann_vol"]).copy()
    if len(df_valid) < 4:
        print("有效股票数不足, 无法分组")
        return

    n_half = len(df_valid) // 2
    high_vol = df_valid.head(n_half)
    low_vol = df_valid.tail(n_half)

    print(f"\n高波动组 (前 {n_half} 只, 年化波动 > {high_vol['ann_vol'].min():.1%}):")
    print(f"  总盈亏: {high_vol['total_pnl'].sum():>12,.0f}")
    print(f"  交易数: {high_vol['n_trades'].sum():>12}")
    print(f"  胜率:   {high_vol['total_pnl'].gt(0).mean():>12.1%}")
    print(f"  盈利股票占比: {(high_vol['total_pnl'] > 0).mean():>12.1%}")

    print(f"\n低波动组 (后 {n_half} 只, 年化波动 < {low_vol['ann_vol'].max():.1%}):")
    print(f"  总盈亏: {low_vol['total_pnl'].sum():>12,.0f}")
    print(f"  交易数: {low_vol['n_trades'].sum():>12}")
    print(f"  胜率:   {low_vol['total_pnl'].gt(0).mean():>12.1%}")
    print(f"  盈利股票占比: {(low_vol['total_pnl'] > 0).mean():>12.1%}")

    # 5. 模拟筛选: 只保留高波动股的效果
    print_section("模拟筛选: 只保留波动率前 N 只")
    print(f"\n{'筛选数':>6} {'波动率阈值':>12} {'预期总盈亏':>14} {'盈利股票占比':>14}")
    print("-" * 55)
    for n in [5, 10, 15, 20]:
        if n > len(df_valid):
            continue
        top_n = df_valid.head(n)
        total_pnl = top_n["total_pnl"].sum()
        vol_threshold = top_n["ann_vol"].min()
        profit_ratio = (top_n["total_pnl"] > 0).mean()
        print(f"{n:>6} {vol_threshold:>12.1%} {total_pnl:>14,.0f} {profit_ratio:>14.1%}")

    # 6. 盈亏贡献集中度
    print_section("盈亏贡献集中度 (Pareto 分析)")
    df_pnl = df[df["total_pnl"] != 0].copy()
    df_pnl["abs_pnl"] = df_pnl["total_pnl"].abs()
    df_pnl = df_pnl.sort_values("total_pnl", ascending=False).reset_index(drop=True)

    total_positive = df_pnl[df_pnl["total_pnl"] > 0]["total_pnl"].sum()
    total_negative = df_pnl[df_pnl["total_pnl"] < 0]["total_pnl"].sum()
    net_pnl = total_positive + total_negative

    print(f"\n盈利股票总盈亏: {total_positive:>14,.0f}")
    print(f"亏损股票总盈亏: {total_negative:>14,.0f}")
    print(f"净盈亏:         {net_pnl:>14,.0f}")
    print(f"\n盈亏比 (盈利/|亏损|): {total_positive / abs(total_negative):.2f}")

    print(f"\n贡献前 5 名 (盈利):")
    for _, row in df_pnl.head(5).iterrows():
        if row["total_pnl"] > 0:
            print(f"  {row['ts_code']:<14} {row['total_pnl']:>12,.0f}  (波动 {row['ann_vol']:.1%})")

    print(f"\n拖后腿前 5 名 (亏损):")
    for _, row in df_pnl.tail(5).iterrows():
        if row["total_pnl"] < 0:
            print(f"  {row['ts_code']:<14} {row['total_pnl']:>12,.0f}  (波动 {row['ann_vol']:.1%})")

    # 7. 相关性分析
    print_section("波动率与盈亏的相关性")
    corr_pnl = df_valid["ann_vol"].corr(df_valid["total_pnl"])
    corr_winrate = df_valid["ann_vol"].corr(df_valid["win_rate"])
    corr_trades = df_valid["ann_vol"].corr(df_valid["n_trades"])
    print(f"\n年化波动率 vs 总盈亏:   相关系数 = {corr_pnl:+.3f}")
    print(f"年化波动率 vs 胜率:     相关系数 = {corr_winrate:+.3f}")
    print(f"年化波动率 vs 交易次数: 相关系数 = {corr_trades:+.3f}")
    print()
    if corr_pnl > 0.3:
        print("结论: 波动率与盈亏正相关 → 高波动股贡献更多收益, 筛选有效")
    elif corr_pnl < -0.3:
        print("结论: 波动率与盈亏负相关 → 低波动股表现更好, 不应筛选高波动")
    else:
        print("结论: 波动率与盈亏无显著相关性 → 筛选效果有限")


if __name__ == "__main__":
    main()
