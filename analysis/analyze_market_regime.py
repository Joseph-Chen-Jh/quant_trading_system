"""
过去5年(2021-07 ~ 2026-07)沪深300大盘行情阶段分析

目标:
    划分"趋势市"和"震荡市"阶段, 为5年回测提供市场环境背景

分析方法 (多指标交叉验证):
    1. 价格走势: 区间涨跌幅、最高/最低、最大回撤
    2. ADX(14): 趋势强度 (>25 趋势明显, <20 震荡)
    3. MA60 位置: 价格在 MA60 之上占比 (多头排列持续性)
    4. MA60 斜率: 上行/走平/下行
    5. 趋势效率 (Kaufman ER): |区间收益| / sum(|日收益|), 高=单边趋势, 低=震荡
    6. MA60 交叉次数: 频繁穿越=震荡, 持续一侧=趋势

分段方式:
    - 按半年分段 (10段), 便于和之前子区间验证对齐
    - 额外按月输出明细, 识别转折点

用法:
    python tests/analyze_market_regime.py
"""
import os, sys
import unicodedata
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from data.storage.database import DataStore
from strategy.timing.adx_filter import calculate_adx


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


# 5年 = 10 个半年子区间
SUBPERIODS = [
    ("2021-07-01", "2021-12-31", "2021H2"),
    ("2022-01-01", "2022-06-30", "2022H1"),
    ("2022-07-01", "2022-12-31", "2022H2"),
    ("2023-01-01", "2023-06-30", "2023H1"),
    ("2023-07-01", "2023-12-31", "2023H2"),
    ("2024-01-01", "2024-06-30", "2024H1"),
    ("2024-07-01", "2024-12-31", "2024H2"),
    ("2025-01-01", "2025-06-30", "2025H1"),
    ("2025-07-01", "2025-12-31", "2025H2"),
    ("2026-01-01", "2026-07-10", "2026H1"),
]


def classify_regime(row):
    """根据多指标判定市场环境

    评分规则 (越正越趋势, 越负越震荡):
        +1 if ADX均值 > 25
        +1 if 趋势效率 > 0.30
        +1 if |区间收益| > 15% (有方向性)
        +0.5 if MA60 交叉次数 <= 2 (持续一侧=趋势, 弱参考)
        -0.5 if MA60 交叉次数 > 6 (极度频繁穿越=震荡, 弱参考)

    注: MA60 交叉弱化为 ±0.5 (之前为 ±1), 因为上涨途中的正常
        回调也会被算成"穿越", 硬性扣分会把适合MA的上涨行情误判成震荡市。
    """
    score = 0.0
    if row["adx_mean"] > 25:
        score += 1
    if row["efficiency"] > 0.30:
        score += 1
    if abs(row["period_return"]) > 0.15:
        score += 1
    if row["ma60_cross"] > 6:
        score -= 0.5
    elif row["ma60_cross"] <= 2:
        score += 0.5

    if score >= 2:
        return "趋势市"
    elif score < 1:
        return "震荡市"
    else:
        return "中性"


def analyze_subperiod(df_sub):
    """分析单个子区间的市场特征"""
    n = len(df_sub)
    if n < 10:
        return None

    close = df_sub["close"].astype(float)
    period_return = close.iloc[-1] / close.iloc[0] - 1
    high = close.max()
    low = close.min()
    amplitude = high / low - 1  # 振幅

    # 最大回撤
    peak = close.cummax()
    drawdown = (close - peak) / peak
    max_dd = drawdown.min()

    # 年化波动
    daily_ret = close.pct_change().dropna()
    ann_vol = daily_ret.std() * np.sqrt(244)

    # 趋势效率 (Kaufman ER): |净变动| / sum(|每日变动|)
    abs_sum = daily_ret.abs().sum()
    efficiency = abs(period_return) / abs_sum if abs_sum > 0 else 0

    # ADX
    adx_mean = df_sub["adx"].mean()
    adx_gt25 = (df_sub["adx"] > 25).mean()

    # MA60 位置
    above_ma60 = (df_sub["close"] > df_sub["ma60"]).mean()

    # MA60 斜率 (首尾比较, 5日平滑)
    ma60_start = df_sub["ma60_smooth"].iloc[0]
    ma60_end = df_sub["ma60_smooth"].iloc[-1]
    ma60_slope = (ma60_end - ma60_start) / ma60_start

    # MA60 交叉次数 (价格穿越MA60)
    above = df_sub["close"] > df_sub["ma60"]
    crossings = (above != above.shift()).sum() - 1

    result = {
        "n_days": n,
        "period_return": period_return,
        "amplitude": amplitude,
        "max_drawdown": max_dd,
        "ann_vol": ann_vol,
        "efficiency": efficiency,
        "adx_mean": adx_mean,
        "adx_gt25": adx_gt25,
        "above_ma60": above_ma60,
        "ma60_slope": ma60_slope,
        "ma60_cross": crossings,
    }
    result["regime"] = classify_regime(result)
    return result


def main():
    store = DataStore()
    df = store.load_index_daily(ts_code="000300.SH", start="20210101")
    if df.empty:
        print("沪深300数据为空")
        return

    df = df.sort_values("trade_date").reset_index(drop=True)
    df["date_dt"] = pd.to_datetime(df["trade_date"], format="%Y%m%d")

    # 计算指标
    df = calculate_adx(df, period=14)
    df["ma60"] = df["close"].rolling(60).mean()
    df["ma60_smooth"] = df["ma60"].rolling(5).mean()
    df = df.dropna(subset=["adx", "ma60"]).reset_index(drop=True)

    lines = []
    lines.append("=" * 130)
    lines.append("沪深300 过去5年行情阶段分析 (2021-07 ~ 2026-07)")
    lines.append("=" * 130)
    lines.append(f"数据范围: {df['trade_date'].min()} ~ {df['trade_date'].max()}, 共 {len(df)} 个交易日")
    lines.append("")

    # 全局概况
    full_ret = df["close"].iloc[-1] / df["close"].iloc[0] - 1
    full_high = df["close"].max()
    full_low = df["close"].min()
    peak = df["close"].cummax()
    full_max_dd = ((df["close"] - peak) / peak).min()
    lines.append(f"5年累计涨跌: {full_ret:+.2%}")
    lines.append(f"5年最高: {full_high:.2f}, 最低: {full_low:.2f}, 振幅: {full_high/full_low-1:.2%}")
    lines.append(f"5年最大回撤: {full_max_dd:.2%}")
    lines.append("")

    # 半年子区间分析
    # 列定义: (标题, 宽度, 对齐方式)
    half_cols = [
        ("区间", 10, 'left'),
        ("天", 6, 'right'),
        ("区间收益", 11, 'right'),
        ("振幅", 9, 'right'),
        ("最大回撤", 10, 'right'),
        ("年化波动", 9, 'right'),
        ("效率ER", 8, 'right'),
        ("ADX均", 8, 'right'),
        ("ADX>25", 8, 'right'),
        (">MA60", 8, 'right'),
        ("MA60斜率", 10, 'right'),
        ("MA60穿", 8, 'right'),
        ("判定", 8, 'right'),
    ]

    lines.append("=" * 110)
    lines.append("半年子区间市场环境划分")
    lines.append("=" * 110)
    header = "".join(pad(name, w, align) for name, w, align in half_cols)
    lines.append(header)
    lines.append("-" * display_width(header))

    regime_counts = {"趋势市": 0, "震荡市": 0, "中性": 0}
    for start, end, label in SUBPERIODS:
        mask = (df["date_dt"] >= pd.to_datetime(start)) & (df["date_dt"] <= pd.to_datetime(end))
        sub = df[mask].copy()
        r = analyze_subperiod(sub)
        if r is None:
            lines.append(f"{label:<10}数据不足")
            continue

        regime_counts[r["regime"]] = regime_counts.get(r["regime"], 0) + 1
        vals = [
            (label, 10, 'left'),
            (str(r['n_days']), 6, 'right'),
            (f"{r['period_return']:+.2%}", 11, 'right'),
            (f"{r['amplitude']:.2%}", 9, 'right'),
            (f"{r['max_drawdown']:.2%}", 10, 'right'),
            (f"{r['ann_vol']:.2%}", 9, 'right'),
            (f"{r['efficiency']:.3f}", 8, 'right'),
            (f"{r['adx_mean']:.2f}", 8, 'right'),
            (f"{r['adx_gt25']:.2%}", 8, 'right'),
            (f"{r['above_ma60']:.2%}", 8, 'right'),
            (f"{r['ma60_slope']:+.2%}", 10, 'right'),
            (str(r['ma60_cross']), 8, 'right'),
            (r['regime'], 8, 'right'),
        ]
        lines.append("".join(pad(v, w, a) for v, w, a in vals))

    lines.append("")
    lines.append(f"阶段统计: 趋势市 {regime_counts.get('趋势市',0)} 段, "
                 f"震荡市 {regime_counts.get('震荡市',0)} 段, "
                 f"中性 {regime_counts.get('中性',0)} 段")

    # 月度明细
    month_cols = [
        ("月份", 10, 'left'),
        ("天", 5, 'right'),
        ("月收益", 10, 'right'),
        ("振幅", 9, 'right'),
        ("最大回撤", 10, 'right'),
        ("年化波动", 9, 'right'),
        ("效率ER", 8, 'right'),
        ("ADX均", 8, 'right'),
        (">MA60", 8, 'right'),
        ("MA60穿", 7, 'right'),
        ("判定", 8, 'right'),
    ]

    lines.append("")
    lines.append("=" * 100)
    lines.append("月度明细 (识别转折点)")
    lines.append("=" * 100)
    header2 = "".join(pad(name, w, align) for name, w, align in month_cols)
    lines.append(header2)
    lines.append("-" * display_width(header2))

    df["ym"] = df["date_dt"].dt.to_period("M").astype(str)
    for ym, sub in df.groupby("ym"):
        sub = sub.sort_values("trade_date").reset_index(drop=True)
        r = analyze_subperiod(sub)
        if r is None:
            continue
        vals = [
            (ym, 10, 'left'),
            (str(r['n_days']), 5, 'right'),
            (f"{r['period_return']:+.2%}", 10, 'right'),
            (f"{r['amplitude']:.2%}", 9, 'right'),
            (f"{r['max_drawdown']:.2%}", 10, 'right'),
            (f"{r['ann_vol']:.2%}", 9, 'right'),
            (f"{r['efficiency']:.3f}", 8, 'right'),
            (f"{r['adx_mean']:.2f}", 8, 'right'),
            (f"{r['above_ma60']:.2%}", 8, 'right'),
            (str(r['ma60_cross']), 7, 'right'),
            (r['regime'], 8, 'right'),
        ]
        lines.append("".join(pad(v, w, a) for v, w, a in vals))

    # 指标说明
    lines.append("")
    lines.append("=" * 130)
    lines.append("指标说明")
    lines.append("=" * 130)
    lines.append("效率ER (Kaufman Efficiency Ratio) = |区间净收益| / sum(|日收益|)")
    lines.append("  - ER > 0.30: 单边趋势 (净变动占比较大, 日间反复少)")
    lines.append("  - ER < 0.15: 震荡 (日间反复大, 净变动小)")
    lines.append("ADX: 趋势强度指标, >25 趋势明显, <20 震荡")
    lines.append("MA60穿: 价格穿越MA60次数, 多=震荡, 少=趋势")
    lines.append("判定规则: 综合评分 >=2 趋势市, <1 震荡市, 其他中性 (MA60交叉弱化为±0.5)")

    output = "\n".join(lines)
    out_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "output", "market_regime_analysis.txt",
    )
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(output)
    print(output)
    print("\n结果已保存: " + out_path)


if __name__ == "__main__":
    main()
