"""
RSI 策略交易行为深度分析

对比 RSI 基线与 D(2.5) 的交易行为:
- 交易笔数与胜率
- 持股时间分布
- 单笔收益率分布
- 购入公司类型 (按名称关键词分类)
- 各段子区间交易明细

用法:
    python experiments/analyze_rsi_trades.py
"""
import os
import sys
import datetime as _dt
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config.stock_pool_loader import load_pool
from data.storage.database import DataStore
from data.storage.models import init_database
from simulation.account import VirtualAccount
from simulation.order_manager import OrderManager
from simulation.scheduler import SimulationScheduler
from strategy.timing.rsi_revert import RSIRevertStrategy
from strategy.portfolio_runner import PortfolioRunner
from strategy.select_stock.volatility_selector import VolatilitySelector

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

# 行业关键词映射 (按名称简单分类)
INDUSTRY_KEYWORDS = {
    "金融": ["银行", "证券", "保险", "金融", "中信", "招商", "兴业", "浦发", "民生", "光大", "交行", "农行", "工行", "建行", "中行", "新华保险", "中国人寿"],
    "医药": ["医药", "生物", "健康", "医疗", "药业", "制药", "疫苗", "基因", "恒瑞", "药明", "爱尔", "通策", "白云山", "云南白药"],
    "新能源": ["新能源", "锂电", "光伏", "风电", "电池", "宁德", "比亚迪", "隆基", "阳光", "通威", "赣锋", "天齐", "汇川", "亿纬"],
    "科技": ["半导体", "芯片", "电子", "科技", "信息", "软件", "通信", "中兴", "立讯", "海康", "科大", "紫光", "京东方", "TCL", "闻泰", "北方华创"],
    "周期": ["钢铁", "有色", "煤炭", "化工", "材料", "水泥", "铝", "铜", "紫金", "宝钢", "海螺", "万华", "中泰", "洛阳钼业"],
    "消费": ["食品", "饮料", "家电", "零售", "商贸", "茅台", "五粮液", "伊利", "美的", "格力", "海尔", "苏宁", "永辉", "泸州老窖", "汾酒", "古井"],
    "制造": ["汽车", "重工", "机械", "装备", "中联", "三一", "潍柴", "上汽", "长城", "长安", "一拖", "中集"],
    "地产": ["地产", "建筑", "建材", "万科", "保利", "绿地", "华夏", "碧桂园"],
    "公用": ["电力", "能源", "环保", "水务", "燃气", "华能", "国电", "长江电力", "华水电"],
}


def classify_industry(name: str) -> str:
    """按名称关键词推断行业"""
    for industry, keywords in INDUSTRY_KEYWORDS.items():
        for kw in keywords:
            if kw in name:
                return industry
    return "其他"


def run_and_collect(start_date, end_date, label, turnover_sell=False, ratio=2.5):
    """跑单个子区间, 返回 (summary, trades, name_map)"""
    start_yyyymmdd = start_date.replace("-", "")
    end_yyyymmdd = end_date.replace("-", "")

    pool = load_pool("csi300")
    name_map = {s["ts_code"]: s.get("name", s["ts_code"]) for s in pool["stocks"]}

    strategy = RSIRevertStrategy(
        rsi_period=14, oversold=30, overbought=70,
        multi_period=True, trend_adaptive=False,
        turnover_sell=turnover_sell, turnover_sell_ratio=ratio,
    )
    account = VirtualAccount()
    om = OrderManager(account)
    scheduler = SimulationScheduler(account, om)

    vol_selector = VolatilitySelector(
        lookback_days=120, top_n=10, rebalance_freq="monthly", mode="high",
    )
    store = DataStore()
    runner = PortfolioRunner(
        pool, strategy, account, scheduler,
        stop_loss=None, vol_selector=vol_selector,
    )

    start_dt = _dt.datetime.strptime(start_date, "%Y-%m-%d")
    warmup_days = int(120 * 1.6) + 30
    data_start_dt = start_dt - _dt.timedelta(days=warmup_days)
    data_start = data_start_dt.strftime("%Y%m%d")

    runner.load_data(store, data_start)
    if len(runner.stock_data) == 0:
        return {"label": label, "error": "无数据"}, [], name_map

    runner.generate_all_signals()
    runner.run_backtest(trade_start_date=start_yyyymmdd)

    nav_df = pd.DataFrame(account.daily_nav)
    if nav_df.empty:
        return {"label": label, "error": "无净值"}, [], name_map
    nav_df["date_dt"] = pd.to_datetime(nav_df["date"], format="%Y%m%d")
    mask = (nav_df["date_dt"] >= pd.to_datetime(start_date)) & (nav_df["date_dt"] <= pd.to_datetime(end_date))
    sub_nav = nav_df[mask].copy()
    if len(sub_nav) < 10:
        return {"label": label, "error": "净值过少"}, [], name_map
    total_return = sub_nav["nav"].astype(float).iloc[-1] / sub_nav["nav"].astype(float).iloc[0] - 1

    trades = [t for t in account.trade_history if start_yyyymmdd <= str(t["trade_date"]) <= end_yyyymmdd]
    summary = {"label": label, "return": total_return, "n_buys": sum(1 for t in trades if t["direction"] == "BUY"),
               "n_sells": sum(1 for t in trades if t["direction"] == "SELL")}
    return summary, trades, name_map


def pair_trades(trades, name_map):
    """配对 BUY/SELL, 计算持股时间与单笔收益"""
    pairs = []
    open_buys = {}
    for t in sorted(trades, key=lambda x: str(x["trade_date"])):
        code = t["ts_code"]
        if t["direction"] == "BUY":
            if code in open_buys:
                continue  # 跳过加仓
            open_buys[code] = t
        elif t["direction"] == "SELL":
            if code in open_buys:
                buy = open_buys[code]
                buy_date = str(buy["trade_date"])
                sell_date = str(t["trade_date"])
                buy_dt = _dt.datetime.strptime(buy_date, "%Y%m%d")
                sell_dt = _dt.datetime.strptime(sell_date, "%Y%m%d")
                hold_days = (sell_dt - buy_dt).days
                buy_price = buy["price"]
                sell_price = t["price"]
                ret = (sell_price - buy_price) / buy_price
                name = name_map.get(code, code)
                pairs.append({
                    "ts_code": code, "name": name, "industry": classify_industry(name),
                    "buy_date": buy_date, "sell_date": sell_date,
                    "hold_days": hold_days, "trade_days": int(hold_days / 1.4),
                    "buy_price": round(buy_price, 2), "sell_price": round(sell_price, 2),
                    "return_pct": ret, "pnl": t.get("pnl", 0) or 0,
                })
                del open_buys[code]
    return pairs


def print_report(title, all_pairs, all_summaries):
    """输出分析报告"""
    print(f"\n{'='*80}")
    print(f"  {title}")
    print(f"{'='*80}")

    # 1. 各段交易笔数
    print(f"\n--- 各段子区间交易笔数 ---")
    print(f"{'区间':<10}{'收益':<10}{'买入':<6}{'卖出':<6}{'配对数':<8}")
    for s in all_summaries:
        if "error" in s:
            print(f"{s['label']:<10}ERROR")
            continue
        print(f"{s['label']:<10}{s['return']:<10.2%}{s['n_buys']:<6}{s['n_sells']:<6}{len([p for p in all_pairs if p['buy_date'][:6] >= s['label'][:4] + ('01' if 'H1' in s['label'] else '07')]):<8}")

    if not all_pairs:
        print("无交易记录")
        return

    # 2. 持股时间分布
    hold_days = [p["trade_days"] for p in all_pairs]
    print(f"\n--- 持股时间分布 (交易日) ---")
    print(f"总交易笔数: {len(all_pairs)}")
    print(f"均值: {np.mean(hold_days):.1f} 天")
    print(f"中位数: {np.median(hold_days):.1f} 天")
    print(f"最短: {min(hold_days)} 天 / 最长: {max(hold_days)} 天")
    # 分桶
    buckets = {"1-5天": 0, "6-10天": 0, "11-20天": 0, "21-30天": 0, "31-60天": 0, "60天+": 0}
    for d in hold_days:
        if d <= 5: buckets["1-5天"] += 1
        elif d <= 10: buckets["6-10天"] += 1
        elif d <= 20: buckets["11-20天"] += 1
        elif d <= 30: buckets["21-30天"] += 1
        elif d <= 60: buckets["31-60天"] += 1
        else: buckets["60天+"] += 1
    print("分桶:")
    for b, c in buckets.items():
        pct = c / len(all_pairs) * 100
        print(f"  {b:<10}: {c:>3} 笔 ({pct:.1f}%)")

    # 3. 单笔收益率分布
    rets = [p["return_pct"] for p in all_pairs]
    wins = [r for r in rets if r > 0]
    losses = [r for r in rets if r <= 0]
    print(f"\n--- 单笔收益率分布 ---")
    print(f"总笔数: {len(rets)} / 胜: {len(wins)} / 负: {len(losses)}")
    print(f"胜率: {len(wins)/len(rets)*100:.1f}%")
    print(f"均值: {np.mean(rets):.2%} / 中位数: {np.median(rets):.2%}")
    print(f"最大盈利: {max(rets):.2%} / 最大亏损: {min(rets):.2%}")
    if wins:
        print(f"平均盈利: {np.mean(wins):.2%}")
    if losses:
        print(f"平均亏损: {np.mean(losses):.2%}")
    # 盈亏比
    if wins and losses:
        avg_win = np.mean(wins)
        avg_loss = abs(np.mean(losses))
        print(f"盈亏比: {avg_win/avg_loss:.2f}")

    # 4. 行业分布
    industries = {}
    for p in all_pairs:
        ind = p["industry"]
        if ind not in industries:
            industries[ind] = {"count": 0, "wins": 0, "total_ret": 0.0}
        industries[ind]["count"] += 1
        if p["return_pct"] > 0:
            industries[ind]["wins"] += 1
        industries[ind]["total_ret"] += p["return_pct"]
    print(f"\n--- 购入公司行业分布 ---")
    print(f"{'行业':<8}{'笔数':<6}{'占比':<8}{'胜率':<8}{'平均收益':<10}")
    for ind, d in sorted(industries.items(), key=lambda x: -x[1]["count"]):
        pct = d["count"] / len(all_pairs) * 100
        wr = d["wins"] / d["count"] * 100
        avg_ret = d["total_ret"] / d["count"]
        print(f"{ind:<8}{d['count']:<6}{pct:<8.1f}{wr:<8.1f}{avg_ret:<10.2%}")

    # 5. 买入股票明细 (按买入次数排序)
    stock_stats = {}
    for p in all_pairs:
        code = p["ts_code"]
        if code not in stock_stats:
            stock_stats[code] = {"name": p["name"], "industry": p["industry"], "trades": 0, "wins": 0, "total_ret": 0.0}
        stock_stats[code]["trades"] += 1
        if p["return_pct"] > 0:
            stock_stats[code]["wins"] += 1
        stock_stats[code]["total_ret"] += p["return_pct"]
    print(f"\n--- 买入股票明细 (按次数排序, 前20) ---")
    print(f"{'代码':<12}{'名称':<10}{'行业':<8}{'次数':<6}{'胜率':<8}{'平均收益':<10}")
    for code, d in sorted(stock_stats.items(), key=lambda x: -x[1]["trades"])[:20]:
        wr = d["wins"] / d["trades"] * 100
        avg_ret = d["total_ret"] / d["trades"]
        print(f"{code:<12}{d['name']:<10}{d['industry']:<8}{d['trades']:<6}{wr:<8.1f}{avg_ret:<10.2%}")

    # 6. 所有交易明细 (按时间排序)
    print(f"\n--- 所有交易明细 (按买入日期) ---")
    print(f"{'买入日':<10}{'卖出日':<10}{'代码':<12}{'名称':<10}{'行业':<8}{'持股天':<8}{'买入价':<8}{'卖出价':<8}{'收益率':<10}")
    for p in sorted(all_pairs, key=lambda x: x["buy_date"]):
        print(f"{p['buy_date']:<10}{p['sell_date']:<10}{p['ts_code']:<12}{p['name']:<10}{p['industry']:<8}{p['trade_days']:<8}{p['buy_price']:<8}{p['sell_price']:<8}{p['return_pct']:<10.2%}")


def main():
    init_database()
    lookback = 120

    # === 基线 ===
    print("\n" + "#"*80)
    print("#  跑 RSI 基线 (无换手率卖出)")
    print("#"*80)
    base_summaries, base_all_pairs = [], []
    for start, end, label in SUBPERIODS_10:
        print(f"\n--- {label} ---")
        s, trades, name_map = run_and_collect(start, end, label, turnover_sell=False)
        base_summaries.append(s)
        if "error" not in s:
            pairs = pair_trades(trades, name_map)
            base_all_pairs.extend(pairs)
            print(f"  收益: {s['return']:.2%}, 买入: {s['n_buys']}, 卖出: {s['n_sells']}, 配对: {len(pairs)}")

    # === D(2.5) ===
    print("\n" + "#"*80)
    print("#  跑 RSI + D(2.5) (换手率高位放量卖出)")
    print("#"*80)
    d_summaries, d_all_pairs = [], []
    for start, end, label in SUBPERIODS_10:
        print(f"\n--- {label} ---")
        s, trades, name_map = run_and_collect(start, end, label, turnover_sell=True, ratio=2.5)
        d_summaries.append(s)
        if "error" not in s:
            pairs = pair_trades(trades, name_map)
            d_all_pairs.extend(pairs)
            print(f"  收益: {s['return']:.2%}, 买入: {s['n_buys']}, 卖出: {s['n_sells']}, 配对: {len(pairs)}")

    # === 分析报告 ===
    print_report("RSI 基线 交易行为分析", base_all_pairs, base_summaries)
    print_report("RSI + D(2.5) 交易行为分析", d_all_pairs, d_summaries)

    # === 对比汇总 ===
    print(f"\n{'='*80}")
    print(f"  基线 vs D(2.5) 对比汇总")
    print(f"{'='*80}")
    print(f"{'指标':<20}{'基线':<20}{'D(2.5)':<20}{'差异':<20}")
    b, d = base_all_pairs, d_all_pairs
    if b and d:
        print(f"{'总交易笔数':<20}{len(b):<20}{len(d):<20}{len(d)-len(b):<20}")
        b_wr = sum(1 for p in b if p["return_pct"] > 0) / len(b) * 100
        d_wr = sum(1 for p in d if p["return_pct"] > 0) / len(d) * 100
        print(f"{'胜率':<20}{b_wr:<20.1f}{d_wr:<20.1f}{d_wr-b_wr:<20.1f}")
        b_hold = np.mean([p["trade_days"] for p in b])
        d_hold = np.mean([p["trade_days"] for p in d])
        print(f"{'平均持股(交易日)':<20}{b_hold:<20.1f}{d_hold:<20.1f}{d_hold-b_hold:<20.1f}")
        b_ret = np.mean([p["return_pct"] for p in b])
        d_ret = np.mean([p["return_pct"] for p in d])
        print(f"{'平均单笔收益':<20}{b_ret:<20.2%}{d_ret:<20.2%}{d_ret-b_ret:<20.2%}")
        b_wins = [p["return_pct"] for p in b if p["return_pct"] > 0]
        d_wins = [p["return_pct"] for p in d if p["return_pct"] > 0]
        b_losses = [p["return_pct"] for p in b if p["return_pct"] <= 0]
        d_losses = [p["return_pct"] for p in d if p["return_pct"] <= 0]
        if b_wins and d_wins:
            print(f"{'平均盈利':<20}{np.mean(b_wins):<20.2%}{np.mean(d_wins):<20.2%}{np.mean(d_wins)-np.mean(b_wins):<20.2%}")
        if b_losses and d_losses:
            print(f"{'平均亏损':<20}{np.mean(b_losses):<20.2%}{np.mean(d_losses):<20.2%}{np.mean(d_losses)-np.mean(b_losses):<20.2%}")
        if b_wins and b_losses and d_wins and d_losses:
            b_ratio = np.mean(b_wins) / abs(np.mean(b_losses))
            d_ratio = np.mean(d_wins) / abs(np.mean(d_losses))
            print(f"{'盈亏比':<20}{b_ratio:<20.2f}{d_ratio:<20.2f}{d_ratio-b_ratio:<20.2f}")


if __name__ == "__main__":
    main()
