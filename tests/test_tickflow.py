"""
TickFlow 数据源可用性测试

验证项:
  1. 能否 import tickflow
  2. TickFlow.free() 能否初始化
  3. 单只股票日K能否拉取
  4. 返回 DataFrame 的列结构
  5. ts_code 格式是否与现有系统一致 (000001.SZ)
  6. 批量拉取是否可用
  7. 数据内容是否合理 (价格、成交量量级)

用法:
  python tests/test_tickflow.py
"""
import os
import sys

# 注入项目根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_import():
    """测试 1: 能否 import"""
    print("\n[1/6] 测试 import tickflow...")
    try:
        from tickflow import TickFlow
        print("  ✓ import 成功")
        return TickFlow
    except ImportError as e:
        print(f"  ✗ import 失败: {e}")
        print("  请先安装: pip install \"tickflow[all]\" --upgrade")
        return None


def test_init(TickFlow):
    """测试 2: 免费层初始化"""
    print("\n[2/6] 测试 TickFlow.free() 初始化...")
    try:
        tf = TickFlow.free()
        print("  ✓ 初始化成功 (免费层, 无需 API key)")
        return tf
    except Exception as e:
        print(f"  ✗ 初始化失败: {e}")
        return None


def test_single_kline(tf):
    """测试 3: 单只股票日K线"""
    print("\n[3/6] 测试单只股票日K线 (000001.SZ 平安银行)...")
    try:
        df = tf.klines.get(
            "000001.SZ",
            period="1d",
            count=100,
            as_dataframe=True,
        )
        if df is None or df.empty:
            print("  ✗ 返回空数据")
            return None

        print(f"  ✓ 拉取成功: {len(df)} 行")
        print(f"  列名: {df.columns.tolist()}")
        print(f"  前 3 行:")
        print(df.head(3).to_string(index=False).replace("\n", "\n    "))
        print(f"  后 3 行:")
        print(df.tail(3).to_string(index=False).replace("\n", "\n    "))

        # 检查必要列是否存在
        required = ["open", "high", "low", "close", "volume"]
        missing = [c for c in required if c not in df.columns]
        if missing:
            print(f"  ⚠ 缺少必要列: {missing}")
        else:
            print(f"  ✓ 必要列齐全: {required}")

        return df
    except Exception as e:
        print(f"  ✗ 拉取失败: {e}")
        return None


def test_data_sanity(df):
    """测试 4: 数据合理性"""
    print("\n[4/6] 测试数据合理性...")
    if df is None or df.empty:
        print("  跳过 (无数据)")
        return

    # 价格合理性: high >= low, open/close 在 [low, high]
    if all(c in df.columns for c in ["open", "high", "low", "close"]):
        bad = ((df["high"] < df["low"]).sum()
               + (df["open"] > df["high"]).sum()
               + (df["open"] < df["low"]).sum()
               + (df["close"] > df["high"]).sum()
               + (df["close"] < df["low"]).sum())
        if bad == 0:
            print("  ✓ OHLC 逻辑正确 (high >= low, open/close 在区间内)")
        else:
            print(f"  ⚠ 发现 {bad} 条异常 OHLC 数据")

    # 价格量级: 平安银行应在 5-20 元区间
    if "close" in df.columns:
        avg_close = df["close"].mean()
        if 1 < avg_close < 100:
            print(f"  ✓ 收盘价均值 {avg_close:.2f} 元, 量级合理")
        else:
            print(f"  ⚠ 收盘价均值 {avg_close:.2f}, 可能异常")

    # 成交量 > 0
    if "volume" in df.columns:
        zero_vol = (df["volume"] <= 0).sum()
        if zero_vol == 0:
            print(f"  ✓ 成交量全部 > 0")
        else:
            print(f"  ⚠ {zero_vol} 条成交量为 0 (可能停牌)")


def test_batch(tf):
    """测试 5: 批量拉取"""
    print("\n[5/6] 测试批量拉取 (3 只股票)...")
    try:
        symbols = ["000001.SZ", "300750.SZ", "600519.SH"]
        dfs = tf.klines.batch(
            symbols,
            period="1d",
            count=50,
            as_dataframe=True,
            show_progress=False,
        )
        if not dfs:
            print("  ✗ 返回空")
            return

        print(f"  ✓ 批量拉取成功: {len(dfs)} 只股票")
        for sym, df in dfs.items():
            rows = len(df) if df is not None and not df.empty else 0
            print(f"    {sym}: {rows} 行")
    except Exception as e:
        print(f"  ✗ 批量拉取失败: {e}")
        print("  (批量接口可能需要 API key, 免费层不支持)")


def test_universe(tf):
    """测试 6: 标的池查询"""
    print("\n[6/6] 测试标的池查询 (CN_Equity_A 全A股)...")
    try:
        universe = tf.universes.get("CN_Equity_A")
        if not universe:
            print("  ✗ 返回空")
            return

        symbols = universe.get("symbols", [])
        print(f"  ✓ 获取全A股标的池: {len(symbols)} 只")
        if symbols:
            print(f"  前 5 个: {symbols[:5]}")
            # 检查格式是否和现有系统一致 (XXXXXX.SZ/SH)
            sample = symbols[0]
            if "." in sample:
                print(f"  ✓ ts_code 格式一致: {sample}")
            else:
                print(f"  ⚠ ts_code 格式不同: {sample} (可能需要转换)")
    except Exception as e:
        print(f"  ✗ 标的池查询失败: {e}")


def main():
    print("=" * 60)
    print("TickFlow 数据源可用性测试")
    print("=" * 60)

    TickFlow = test_import()
    if TickFlow is None:
        return

    tf = test_init(TickFlow)
    if tf is None:
        return

    df = test_single_kline(tf)
    test_data_sanity(df)
    test_batch(tf)
    test_universe(tf)

    print("\n" + "=" * 60)
    print("测试完成。如果以上全部 ✓, 可以考虑集成到项目。")
    print("如果有 ⚠ 或 ✗, 把输出贴给我分析。")
    print("=" * 60)


if __name__ == "__main__":
    main()
