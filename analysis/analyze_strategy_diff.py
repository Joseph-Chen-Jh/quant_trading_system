"""
策略交易股票类型对比分析

用途:
    读取两份交易明细 CSV, 对比两个策略实际交易的股票:
      1. 各自交易了哪些股票, 各交易多少笔, 盈亏分布
      2. 按行业分类 (本地硬编码映射), 对比两个策略偏好的行业
      3. 识别"策略A 独有 / 策略B 独有 / 两者共有"的股票, 揭示互补性

用法:
    # 默认: RSI vs MA
    python analysis/analyze_strategy_diff.py
    # 自定义: 单周期RSI vs 多周期RSI
    python analysis/analyze_strategy_diff.py --file1 output/backtest_trades_rsi.csv --label1 "单周期RSI" --file2 output/backtest_trades_rsi_mp.csv --label2 "多周期RSI"
"""
import os
import sys
import argparse
import time
import unicodedata
import pandas as pd
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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
    """按显示宽度填充对齐"""
    s = str(s)
    fill = max(0, width - display_width(s))
    if align == 'left':
        return s + ' ' * fill
    return ' ' * fill + s


def get_industry_map(ts_codes):
    """根据股票代码/名称映射行业 (本地硬编码, akshare 网络接口不稳定)"""
    # 66 只交易过的股票 → 行业映射 (基于公开信息手工整理)
    industry_map = {
        # ===== 半导体/芯片 =====
        '688981.SH': '半导体',   # 中芯国际
        '688256.SH': '半导体',   # 寒武纪
        '688521.SH': '半导体',   # 芯原股份
        '688008.SH': '半导体',   # 澜起科技
        '603893.SH': '半导体',   # 瑞芯微
        '002049.SZ': '半导体',   # 紫光国微
        '000938.SZ': '半导体',   # 紫光股份
        '002625.SZ': '半导体',   # 光启技术
        '000657.SZ': '半导体',   # 中钨高新
        '000988.SZ': '半导体',   # 华工科技
        # ===== 通信/光模块 =====
        '300308.SZ': '通信',    # 中际旭创
        '300394.SZ': '通信',    # 天孚通信
        '300502.SZ': '通信',    # 新易盛
        '688183.SH': '通信',    # 生益电子
        '000063.SZ': '通信',    # 中兴通讯
        '301165.SZ': '通信',    # 锐捷网络
        # ===== 消费电子 =====
        '300476.SZ': '消费电子',  # 胜宏科技 (PCB)
        '300433.SZ': '消费电子',  # 蓝思科技
        '002600.SZ': '消费电子',  # 领益智造
        '300803.SZ': '消费电子',  # 指南针
        # ===== 软件/IT/AI =====
        '688111.SH': '软件',    # 金山办公
        '301269.SZ': '软件',    # 华大九天
        '300418.SZ': '软件',    # 昆仑万维
        '601360.SH': '软件',    # 三六零
        '300033.SZ': '软件',    # 同花顺
        '002230.SZ': '软件',    # 科大讯飞
        '301236.SZ': '软件',    # 软通动力
        # ===== 新能源/光伏 =====
        '688472.SH': '光伏',    # 阿特斯
        '605117.SH': '光伏',    # 德业股份
        '002202.SZ': '光伏',    # 金风科技
        '002074.SZ': '锂电',    # 国轩高科
        '300450.SZ': '锂电',    # 先导智能
        '300316.SZ': '光伏',    # 晶盛机电
        # ===== 传媒/游戏 =====
        '300251.SZ': '传媒',    # 光线传媒
        '002027.SZ': '传媒',    # 分众传媒
        '002558.SZ': '游戏',    # 巨人网络
        # ===== 食品饮料 =====
        '000858.SZ': '白酒',    # 五粮液
        '000568.SZ': '白酒',    # 泸州老窖
        # ===== 金融 =====
        '000776.SZ': '券商',    # 广发证券
        '000166.SZ': '券商',    # 申万宏源
        # ===== 地产/基建 =====
        '000002.SZ': '地产',    # 万科A
        '001979.SZ': '地产',    # 招商蛇口
        '000425.SZ': '机械',    # 徐工机械
        # ===== 汽车 =====
        '000625.SZ': '汽车',    # 长安汽车
        '601127.SH': '汽车',    # 赛力斯
        # ===== 军工/航天 =====
        '000768.SZ': '军工',    # 中航西飞
        '302132.SZ': '军工',    # 中航成飞
        '600118.SH': '航天',    # 中国卫星
        '601698.SH': '航天',    # 中国卫通
        # ===== 化工/材料 =====
        '002648.SZ': '化工',    # 卫星化学
        '002493.SZ': '化工',    # 荣盛石化
        '000807.SZ': '有色',    # 云铝股份
        '002532.SZ': '有色',    # 天山铝业
        '000630.SZ': '有色',    # 铜陵有色
        '000708.SZ': '钢铁',    # 中信特钢
        # ===== 医药/科技 =====
        '002236.SZ': '安防',    # 大华股份
        '300124.SZ': '工控',    # 汇川技术
        '002001.SZ': '医药',    # 新和成
        # ===== 资源/其他 =====
        '000975.SZ': '有色',    # 山金国际
        '000792.SZ': '盐湖',    # 盐湖股份
        '000617.SZ': '金融',    # 中油资本
        # ===== 航运 =====
        '600026.SH': '航运',    # 中远海能
        '601872.SH': '航运',    # 招商轮船
        # ===== 存储 =====
        '301308.SZ': '半导体',  # 江波龙 (存储芯片)
        '300442.SZ': '通信',    # 润泽科技 (IDC)
    }
    return industry_map


def load_trades(path):
    """加载交易明细, 返回 DataFrame"""
    df = pd.read_csv(path)
    df['trade_date'] = df['trade_date'].astype(str)
    return df


def summarize_trades(df, label):
    """汇总单策略交易: 各股票交易笔数、净盈亏"""
    # 按股票汇总: 买入次数、卖出次数、总盈亏 (卖出pnl之和)
    buy_df = df[df['direction'] == 'BUY']
    sell_df = df[df['direction'] == 'SELL']

    n_buy = buy_df.groupby('ts_code').size().rename('n_buy')
    n_sell = sell_df.groupby('ts_code').size().rename('n_sell')
    pnl = sell_df.groupby('ts_code')['pnl'].sum().rename('net_pnl')

    summary = pd.concat([n_buy, n_sell, pnl], axis=1).fillna(0)
    summary['n_sell'] = summary['n_sell'].astype(int)
    summary['n_buy'] = summary['n_buy'].astype(int)
    summary['net_pnl'] = summary['net_pnl'].astype(float)
    summary = summary.sort_values('net_pnl', ascending=False)
    return summary


def main():
    parser = argparse.ArgumentParser(description="策略交易股票类型对比分析")
    parser.add_argument("--file1", default="output/backtest_trades_rsi.csv", help="策略A交易明细CSV (默认 RSI)")
    parser.add_argument("--label1", default="RSI", help="策略A标签 (默认 RSI)")
    parser.add_argument("--file2", default="output/backtest_trades_ma.csv", help="策略B交易明细CSV (默认 MA)")
    parser.add_argument("--label2", default="MA", help="策略B标签 (默认 MA)")
    args = parser.parse_args()

    base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    output_dir = os.path.join(base_dir, "output")
    file1_path = args.file1 if os.path.isabs(args.file1) else os.path.join(base_dir, args.file1)
    file2_path = args.file2 if os.path.isabs(args.file2) else os.path.join(base_dir, args.file2)

    if not os.path.exists(file1_path) or not os.path.exists(file2_path):
        print(f"[错误] 找不到 trades 文件: {file1_path} / {file2_path}")
        return

    L1, L2 = args.label1, args.label2

    print("=" * 100)
    print(f"{L1} vs {L2} 策略交易股票类型对比分析")
    print("=" * 100)

    t1_trades = load_trades(file1_path)
    t2_trades = load_trades(file2_path)

    print(f"\n{L1} 交易笔数: BUY={len(t1_trades[t1_trades['direction']=='BUY'])}, "
          f"SELL={len(t1_trades[t1_trades['direction']=='SELL'])}")
    print(f"{L2}  交易笔数: BUY={len(t2_trades[t2_trades['direction']=='BUY'])}, "
          f"SELL={len(t2_trades[t2_trades['direction']=='SELL'])}")

    t1_sum = summarize_trades(t1_trades, L1)
    t2_sum = summarize_trades(t2_trades, L2)

    # 加载股票名称 (从 csi300 yaml)
    try:
        import yaml
        yaml_path = os.path.join(base_dir, "config", "stock_pool.yaml")
        with open(yaml_path, encoding='utf-8') as f:
            cfg = yaml.safe_load(f)
        name_map = {s['ts_code']: s.get('name', '') for s in cfg['pools']['csi300']['stocks']}
    except Exception:
        name_map = {}

    # ===== 1. 各策略交易的股票汇总 =====
    print("\n" + "=" * 100)
    print(f"1. {L1} 策略交易的股票明细 (按净盈亏降序)")
    print("=" * 100)
    cols = [
        ("代码", 12, 'left'), ("名称", 10, 'left'), ("行业", 10, 'left'),
        ("买入", 6, 'right'), ("卖出", 6, 'right'), ("净盈亏", 14, 'right'),
    ]
    print("".join(pad(n, w, a) for n, w, a in cols))
    print("-" * 70)
    industry_map = get_industry_map([])
    for code, row in t1_sum.iterrows():
        name = name_map.get(code, '')
        ind = industry_map.get(code, '未知')
        vals = [(code, 12, 'left'), (name, 10, 'left'), (ind, 10, 'left'),
                (str(row['n_buy']), 6, 'right'),
                (str(row['n_sell']), 6, 'right'),
                (f"{row['net_pnl']:>+.0f}", 14, 'right')]
        print("".join(pad(v, w, a) for v, w, a in vals))

    print(f"\n{L1} 交易股票数: {len(t1_sum)}")

    print("\n" + "=" * 100)
    print(f"2. {L2} 策略交易的股票明细 (按净盈亏降序)")
    print("=" * 100)
    print("".join(pad(n, w, a) for n, w, a in cols))
    print("-" * 70)
    for code, row in t2_sum.iterrows():
        name = name_map.get(code, '')
        ind = industry_map.get(code, '未知')
        vals = [(code, 12, 'left'), (name, 10, 'left'), (ind, 10, 'left'),
                (str(row['n_buy']), 6, 'right'),
                (str(row['n_sell']), 6, 'right'),
                (f"{row['net_pnl']:>+.0f}", 14, 'right')]
        print("".join(pad(v, w, a) for v, w, a in vals))

    print(f"\n{L2} 交易股票数: {len(t2_sum)}")

    # ===== 3. 交易股票集合差异 =====
    print("\n" + "=" * 100)
    print("3. 交易股票集合差异 (揭示互补性)")
    print("=" * 100)
    s1_set = set(t1_sum.index)
    s2_set = set(t2_sum.index)
    both = s1_set & s2_set
    s1_only = s1_set - s2_set
    s2_only = s2_set - s1_set
    print(f"{L1} 交易股票数: {len(s1_set)}")
    print(f"{L2}  交易股票数: {len(s2_set)}")
    print(f"两者都交易: {len(both)} 只  ({', '.join(sorted(both)) if both else '无'})")
    print(f"{L1} 独有: {len(s1_only)} 只  ({', '.join(sorted(s1_only)) if s1_only else '无'})")
    print(f"{L2} 独有: {len(s2_only)} 只  ({', '.join(sorted(s2_only)) if s2_only else '无'})")

    # ===== 4. 行业分布对比 =====
    print("\n" + "=" * 100)
    print("4. 行业分布对比 (本地手工分类)")
    print("=" * 100)

    s1_ind = pd.Series([industry_map.get(c, "未知") for c in t1_sum.index],
                        index=t1_sum.index)
    s2_ind = pd.Series([industry_map.get(c, "未知") for c in t2_sum.index],
                       index=t2_sum.index)

    s1_ind_counts = s1_ind.value_counts()
    s2_ind_counts = s2_ind.value_counts()
    all_inds = sorted(set(s1_ind_counts.index) | set(s2_ind_counts.index))

    print("\n各行业交易股票数对比:")
    cols = [
        ("行业", 16, 'left'), (f"{L1}股票数", 14, 'right'),
        (f"{L2}股票数", 14, 'right'), (f"{L1}净盈亏", 14, 'right'),
        (f"{L2}净盈亏", 14, 'right'),
    ]
    print("".join(pad(n, w, a) for n, w, a in cols))
    print("-" * 80)
    for ind in all_inds:
        s1_n = int(s1_ind_counts.get(ind, 0))
        s2_n = int(s2_ind_counts.get(ind, 0))
        s1_pnl = t1_sum[s1_ind == ind]['net_pnl'].sum()
        s2_pnl = t2_sum[s2_ind == ind]['net_pnl'].sum()
        vals = [(ind, 16, 'left'), (str(s1_n), 14, 'right'),
                (str(s2_n), 14, 'right'),
                (f"{s1_pnl:>+.0f}", 14, 'right'),
                (f"{s2_pnl:>+.0f}", 14, 'right')]
        print("".join(pad(v, w, a) for v, w, a in vals))

    # ===== 5. 两者都交易的股票盈亏对比 =====
    print("\n" + "=" * 100)
    print(f"5. 两者都交易的股票: {L1} vs {L2} 净盈亏对比")
    print("=" * 100)
    if both:
        cols = [
            ("代码", 12, 'left'), ("名称", 10, 'left'), ("行业", 10, 'left'),
            (f"{L1}净盈亏", 14, 'right'), (f"{L2}净盈亏", 14, 'right'),
            (f"差异({L1}-{L2})", 16, 'right'),
        ]
        print("".join(pad(n, w, a) for n, w, a in cols))
        print("-" * 80)
        for code in sorted(both):
            r = t1_sum.loc[code, 'net_pnl']
            m = t2_sum.loc[code, 'net_pnl']
            name = name_map.get(code, '')
            ind = industry_map.get(code, '未知')
            vals = [(code, 12, 'left'), (name, 10, 'left'), (ind, 10, 'left'),
                    (f"{r:>+.0f}", 14, 'right'),
                    (f"{m:>+.0f}", 14, 'right'), (f"{r-m:>+.0f}", 16, 'right')]
            print("".join(pad(v, w, a) for v, w, a in vals))
    else:
        print("无共交易股票")

    # ===== 6. L1 独有股票的盈亏 =====
    print("\n" + "=" * 100)
    print(f"6. {L1} 独有交易股票 ({L2} 未触发)")
    print("=" * 100)
    if s1_only:
        cols = [
            ("代码", 12, 'left'), ("名称", 10, 'left'), ("行业", 10, 'left'),
            ("买入", 6, 'right'), ("卖出", 6, 'right'), ("净盈亏", 14, 'right'),
        ]
        print("".join(pad(n, w, a) for n, w, a in cols))
        print("-" * 70)
        for code in sorted(s1_only):
            row = t1_sum.loc[code]
            ind = industry_map.get(code, "未知")
            name = name_map.get(code, '')
            vals = [(code, 12, 'left'), (name, 10, 'left'), (ind, 10, 'left'),
                    (str(int(row['n_buy'])), 6, 'right'),
                    (str(int(row['n_sell'])), 6, 'right'),
                    (f"{row['net_pnl']:>+.0f}", 14, 'right')]
            print("".join(pad(v, w, a) for v, w, a in vals))
    else:
        print("无")

    print("\n" + "=" * 100)
    print(f"7. {L2} 独有交易股票 ({L1} 未触发)")
    print("=" * 100)
    if s2_only:
        cols = [
            ("代码", 12, 'left'), ("名称", 10, 'left'), ("行业", 10, 'left'),
            ("买入", 6, 'right'), ("卖出", 6, 'right'), ("净盈亏", 14, 'right'),
        ]
        print("".join(pad(n, w, a) for n, w, a in cols))
        print("-" * 70)
        for code in sorted(s2_only):
            row = t2_sum.loc[code]
            ind = industry_map.get(code, "未知")
            name = name_map.get(code, '')
            vals = [(code, 12, 'left'), (name, 10, 'left'), (ind, 10, 'left'),
                    (str(int(row['n_buy'])), 6, 'right'),
                    (str(int(row['n_sell'])), 6, 'right'),
                    (f"{row['net_pnl']:>+.0f}", 14, 'right')]
            print("".join(pad(v, w, a) for v, w, a in vals))
    else:
        print("无")

    # 保存结果到文本
    print(f"\n[提示] 本脚本仅输出到终端, 如需保存请重定向: python analysis/analyze_strategy_diff.py > output/strategy_diff_analysis.txt")


if __name__ == "__main__":
    main()
