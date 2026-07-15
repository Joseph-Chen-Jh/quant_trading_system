"""
回测结果分析工具

读取 backtest_nav.csv 和 backtest_trades.csv,
计算并打印详细的绩效指标 (收益/回撤/夏普/胜率/月度收益/个股统计).

用法:
    python analysis/analyze_backtest.py
    python analysis/analyze_backtest.py --nav path/to/nav.csv --trades path/to/trades.csv
"""
import os
import sys
import argparse
import unicodedata

import pandas as pd
import numpy as np


def display_width(s: str) -> int:
    """计算字符串在终端的显示宽度 (CJK/全角占2, 其余占1)"""
    w = 0
    for ch in str(s):
        if unicodedata.east_asian_width(ch) in ('F', 'W'):
            w += 2
        else:
            w += 1
    return w


def pad(s, width: int, align: str = 'left') -> str:
    """按显示宽度填充对齐 (align: 'left' 或 'right')"""
    s = str(s)
    fill = max(0, width - display_width(s))
    if align == 'left':
        return s + ' ' * fill
    return ' ' * fill + s

# 确保项目根目录在 path 中
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _PROJECT_ROOT)

from monitor.report_viewer import BacktestReport, find_default_report


def format_pct(v: float, with_sign: bool = True) -> str:
    """格式化百分比"""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "  N/A"
    sign = "+" if with_sign and v >= 0 else ""
    return f"{sign}{v * 100:.2f}%"


def format_num(v: float, decimals: int = 2) -> str:
    """格式化数值"""
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return "N/A"
    return f"{v:.{decimals}f}"


def print_summary(report: BacktestReport):
    """打印核心绩效指标"""
    m = report.compute_metrics()

    print("\n" + "=" * 60)
    print("  回测绩效分析报告")
    print("=" * 60)

    # --- 收益指标 ---
    print("\n┌─ 收益指标 ─────────────────────────────────┐")
    print(f"│  初始资产:    ¥{m.get('initial_asset', 0):>15,.0f}")
    print(f"│  最终资产:    ¥{m.get('final_asset', 0):>15,.0f}")
    print(f"│  累计收益率:  {format_pct(m.get('total_return')):>15}")
    print(f"│  年化收益率:  {format_pct(m.get('ann_return')):>15}")
    print(f"│  交易天数:    {m.get('n_days', 0):>15}")
    print("└────────────────────────────────────────────┘")

    # --- 风险指标 ---
    print("\n┌─ 风险指标 ─────────────────────────────────┐")
    print(f"│  最大回撤:    {format_pct(m.get('max_drawdown', 0), with_sign=False):>15}")
    print(f"│  回撤日期:    {str(m.get('max_dd_date', 'N/A')):>15}")
    print(f"│  年化波动率:  {format_pct(m.get('ann_vol', 0), with_sign=False):>15}")
    print(f"│  夏普比率:    {format_num(m.get('sharpe', 0)):>15}")
    print("└────────────────────────────────────────────┘")

    # --- 基准对比 ---
    has_benchmark = "benchmark_return" in m
    has_buyhold = "buyhold_return" in m

    if has_benchmark or has_buyhold:
        print("\n┌─ 基准对比 ─────────────────────────────────┐")
        if has_buyhold:
            print(f"│  买入持有收益:    {format_pct(m.get('buyhold_return')):>15}")
            print(f"│  买入持有回撤:    {format_pct(m.get('buyhold_max_dd', 0), with_sign=False):>15}")
            print(f"│  买入持有夏普:    {format_num(m.get('buyhold_sharpe', 0)):>15}")
            print(f"│  超额(vs买入持有):{format_pct(m.get('excess_vs_buyhold', 0)):>15}")
        if has_benchmark:
            print(f"│  沪深300收益:     {format_pct(m.get('benchmark_return')):>15}")
            print(f"│  沪深300回撤:     {format_pct(m.get('benchmark_max_dd', 0), with_sign=False):>15}")
            print(f"│  超额(vs沪深300): {format_pct(m.get('excess_vs_benchmark', 0)):>15}")
            if "tracking_error" in m:
                print(f"│  跟踪误差:        {format_pct(m.get('tracking_error', 0), with_sign=False):>15}")
            if "information_ratio" in m:
                print(f"│  信息比率:        {format_num(m.get('information_ratio', 0)):>15}")
        print("└────────────────────────────────────────────┘")

    # --- 交易统计 ---
    if "n_trades" in m:
        print("\n┌─ 交易统计 ─────────────────────────────────┐")
        print(f"│  总交易笔数:  {m.get('n_trades', 0):>15}")
        print(f"│  胜率:        {format_pct(m.get('win_rate', 0), with_sign=False):>15}")
        print(f"│  盈利笔数:    {m.get('n_wins', 0):>15}")
        print(f"│  亏损笔数:    {m.get('n_losses', 0):>15}")
        if "avg_win" in m:
            print(f"│  平均盈利:    ¥{m['avg_win']:>14,.0f}")
        if "avg_loss" in m:
            print(f"│  平均亏损:    ¥{m['avg_loss']:>14,.0f}")
        if "profit_loss_ratio" in m:
            print(f"│  盈亏比:      {format_num(m.get('profit_loss_ratio', 0)):>15}")
        if "expectancy" in m:
            print(f"│  期望收益:    ¥{m['expectancy']:>14,.0f}")
        if "total_cost" in m:
            print(f"│  总手续费:    ¥{m.get('total_cost', 0):>14,.0f}")
        if "avg_hold_days" in m:
            print(f"│  平均持有天数: {format_num(m.get('avg_hold_days', 0), 1):>14}")
        print("└────────────────────────────────────────────┘")


def print_monthly_returns(report: BacktestReport):
    """打印月度收益率表"""
    m = report.compute_metrics()
    monthly = m.get("monthly_returns")
    if monthly is None or monthly.empty:
        return

    print("\n" + "=" * 60)
    print("  月度收益率")
    print("=" * 60)

    # 列宽 (显示宽度)
    year_w = 6
    col_w = 8

    # 表头
    header = pad("年份", year_w, 'left')
    for mo in range(1, 13):
        header += pad(f"{mo}月", col_w, 'right')
    header += pad("全年", col_w, 'right')
    print(header)
    print("-" * display_width(header))

    for year, row in monthly.iterrows():
        line = pad(str(year), year_w, 'left')
        for mo in range(1, 13):
            val = row.get(mo, np.nan)
            if pd.isna(val):
                line += ' ' * col_w
            else:
                line += pad(f"{val*100:>+7.2f}%", col_w, 'right')
        total = row.get("全年", np.nan)
        if not pd.isna(total):
            line += pad(f"{total*100:>+7.2f}%", col_w, 'right')
        print(line)


def print_per_stock_stats(report: BacktestReport):
    """打印个股交易统计"""
    df = report.get_per_stock_stats()
    if df.empty:
        return

    print("\n" + "=" * 60)
    print("  个股交易统计")
    print("=" * 60)

    # 截断显示前20只
    display = df.head(20)

    # 列宽 (显示宽度)
    cols = [
        ("代码", 12, 'left'),
        ("买入", 6, 'right'),
        ("卖出", 6, 'right'),
        ("胜率", 8, 'right'),
        ("总盈亏", 12, 'right'),
        ("净盈亏", 12, 'right'),
        ("持有天数", 10, 'right'),
    ]

    # 表头
    header = "".join(pad(name, w, align) for name, w, align in cols)
    print(header)
    print("-" * display_width(header))

    for _, row in display.iterrows():
        vals = [
            (str(row['ts_code']), 12, 'left'),
            (str(int(row['买入次数'])), 6, 'right'),
            (str(int(row['卖出次数'])), 6, 'right'),
            (f"{row['胜率']*100:.1f}%", 8, 'right'),
            (f"{row['总盈亏']:,.0f}", 12, 'right'),
            (f"{row['净盈亏']:,.0f}", 12, 'right'),
            (str(int(row['平均持有天数'])), 10, 'right'),
        ]
        print("".join(pad(v, w, a) for v, w, a in vals))

    if len(df) > 20:
        print(f"\n  ... 共 {len(df)} 只股票, 仅显示前 20 只")


def main():
    parser = argparse.ArgumentParser(description="回测结果分析工具")
    parser.add_argument("--nav", help="净值CSV路径 (默认: backtest_nav.csv)")
    parser.add_argument("--trades", help="交易明细CSV路径 (默认: backtest_trades.csv)")
    args = parser.parse_args()

    # 定位文件
    if args.nav and args.trades:
        nav_path, trades_path = args.nav, args.trades
    else:
        nav_path, trades_path = find_default_report()

    # 检查文件
    if not os.path.exists(nav_path):
        print(f"错误: 净值文件不存在: {nav_path}")
        print("请先运行回测生成 backtest_nav.csv")
        sys.exit(1)
    if not os.path.exists(trades_path):
        print(f"错误: 交易明细文件不存在: {trades_path}")
        print("请先运行回测生成 backtest_trades.csv")
        sys.exit(1)

    print(f"加载: {nav_path}")
    print(f"加载: {trades_path}")

    nav = pd.read_csv(nav_path, dtype={"date": str})
    trades = pd.read_csv(trades_path, dtype={"trade_date": str})

    print(f"净值记录: {len(nav)} 行, 交易记录: {len(trades)} 行")

    report = BacktestReport(nav=nav, trades=trades)

    print_summary(report)
    print_monthly_returns(report)
    print_per_stock_stats(report)

    print("\n" + "=" * 60)
    print("  分析完成")
    print("=" * 60)


if __name__ == "__main__":
    main()
