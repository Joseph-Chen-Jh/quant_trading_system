"""
PE 数据获取脚本

从 akshare 拉取历史 PE 数据, 写入 quant.db 的 pe_history 表.

akshare 接口:
    ak.stock_a_lg_indicator(symbol="000001")
    返回: trade_date, pe, pe_ttm, pb, ps, ps_ttm, dv_ratio, dv_ttm, total_mv

用法:
    python data/fetcher/fetch_pe_data.py --codes 000001.SZ,300750.SZ,600519.SH
    python data/fetcher/fetch_pe_data.py --pool default

输出:
    quant.db: pe_history 表 (ts_code + trade_date 联合主键)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import time
import argparse
import pandas as pd
from loguru import logger

from config.settings import AKSHARE_REQUEST_INTERVAL
from data.storage.database import DataStore
from data.storage.models import init_database


def _fetch_pe_from_lg(symbol: str) -> pd.DataFrame:
    """数据源1: 乐咕乐股 (stock_a_lg_indicator)"""
    import akshare as ak
    df = ak.stock_a_lg_indicator(symbol=symbol)
    if df is None or df.empty:
        return pd.DataFrame()
    col_map = {"日期": "trade_date", "市盈率": "pe"}
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    return df


def _fetch_pe_from_baidu(symbol: str) -> pd.DataFrame:
    """数据源: 百度股市通 (stock_zh_valuation_baidu)

    返回列: date (YYYY-MM-DD), value (PE 数值)
    period: 近一年/近三年/近五年/全部
    indicator: 市盈率(TTM) / 市净率 / 市销率(TTM)
    """
    import akshare as ak
    df = ak.stock_zh_valuation_baidu(
        symbol=symbol, period="近五年", indicator="市盈率(TTM)"
    )
    if df is None or df.empty:
        return pd.DataFrame()
    # 百度接口返回列名: date, value
    df = df.rename(columns={"date": "trade_date", "value": "pe"})
    return df


def fetch_pe_single(ts_code: str) -> pd.DataFrame:
    """
    拉取单只股票的历史 PE 数据 (多数据源 fallback)

    优先级:
      1. 百度股市通 stock_zh_valuation_baidu (近五年, 当前 akshare 版本可用)
      2. 乐咕乐股 stock_a_lg_indicator (历史 PE 最全, 新版 akshare 已移除)

    Returns:
        DataFrame: ts_code, trade_date, pe
    """
    symbol = ts_code.split(".")[0]
    df = pd.DataFrame()

    # 数据源1: 百度股市通 (当前版本 akshare 可用)
    try:
        df = _fetch_pe_from_baidu(symbol)
        if not df.empty:
            logger.debug(f"{ts_code} 从百度股市通获取 PE: {len(df)} 行")
    except Exception as e:
        logger.debug(f"{ts_code} 百度股市通失败: {e}")

    # 数据源2: 乐咕乐股 (旧版 akshare 才有, 作为兼容保留)
    if df.empty:
        try:
            df = _fetch_pe_from_lg(symbol)
            if not df.empty:
                logger.debug(f"{ts_code} 从乐咕乐股获取 PE: {len(df)} 行")
        except (Exception, AttributeError) as e:
            logger.debug(f"{ts_code} 乐咕乐股失败: {e}")

    if df is None or df.empty:
        return pd.DataFrame()

    # 列名兼容
    if "trade_date" not in df.columns or "pe" not in df.columns:
        logger.warning(f"{ts_code} PE 数据缺少必要列, 实际列: {list(df.columns)}")
        return pd.DataFrame()

    # 标准化 trade_date 为 YYYYMMDD
    df["trade_date"] = pd.to_datetime(df["trade_date"]).dt.strftime("%Y%m%d")
    df["ts_code"] = ts_code

    # 过滤无效 PE (负数或 0)
    df = df[df["pe"].notna() & (df["pe"] > 0)]

    return df[["ts_code", "trade_date", "pe"]].sort_values("trade_date").reset_index(drop=True)


def fetch_pe_batch(ts_codes: list, force: bool = False, store: DataStore = None) -> dict:
    """
    批量拉取 PE 数据, 写入 quant.db 的 pe_history 表

    Args:
        ts_codes: 股票代码列表
        force:    是否强制重新拉取 (已有数据也会重新拉取覆盖)
        store:    DataStore 实例 (None 时自动创建)
    Returns:
        {ts_code: DataFrame} 成功拉取的字典
    """
    if store is None:
        init_database()
        store = DataStore()

    pe_data = {}
    success = 0
    failed = []

    for i, ts_code in enumerate(ts_codes, 1):
        # 缓存命中: 数据库已有数据且非强制刷新
        if not force:
            existing = store.load_pe_history(ts_code=ts_code)
            if not existing.empty:
                pe_data[ts_code] = existing
                success += 1
                continue

        # 拉取
        logger.info(f"[{i}/{len(ts_codes)}] 拉取 {ts_code} PE 数据...")
        df = fetch_pe_single(ts_code)

        if df.empty:
            logger.warning(f"[{i}/{len(ts_codes)}] {ts_code} PE 数据为空")
            failed.append(ts_code)
        else:
            store.save_pe_history(df)
            pe_data[ts_code] = df
            success += 1
            logger.info(f"[{i}/{len(ts_codes)}] {ts_code}: {len(df)} 行 PE 数据已写入数据库")

        time.sleep(AKSHARE_REQUEST_INTERVAL)

    logger.info(f"PE 数据拉取完成: {success}/{len(ts_codes)} 成功, {len(failed)} 失败")
    if failed:
        logger.warning(f"失败列表: {failed}")
        logger.info("=" * 60)
        logger.info("PE 数据自动拉取失败, 手动下载方法 (三选一):")
        logger.info("=" * 60)
        logger.info("")
        logger.info("【方案A】akshare 交互式调试 (推荐先试)")
        logger.info("  在 Python 里逐个接口试, 看哪个能返回数据:")
        logger.info("    import akshare as ak")
        logger.info("    df = ak.stock_a_lg_indicator(symbol='000001')       # 乐咕乐股")
        logger.info("    df = ak.stock_zh_valuation_baidu(symbol='300750', period='近五年', indicator='市盈率(TTM)')")
        logger.info("  把能用的接口告诉我, 我更新代码")
        logger.info("")
        logger.info("【方案B】东方财富网页下载")
        logger.info("  1. 打开 https://data.eastmoney.com/bkzj/hy.html")
        logger.info("  2. 或个股页面: https://quote.eastmoney.com/sz300750.html")
        logger.info("  3. 找'财务分析'→'估值分析', 下载历史 PE")
        logger.info("  4. CSV 必须包含 trade_date 和 pe 两列 (中文列名 日期/市盈率 也可)")
        logger.info("  5. 告诉我文件路径, 我帮你导入数据库")
        logger.info("")
        logger.info("【方案C】改用低PE绝对值策略 (只需最新PE)")
        logger.info("  如果历史PE实在拿不到, 可以降级用'选PE最低的N只'策略")
        logger.info("  只需 ak.stock_zh_a_spot_em() 一次性拉全市场最新PE快照")
        logger.info("  告诉我'改用方案C', 我切换策略变体")
        logger.info("=" * 60)

    return pe_data


def main():
    parser = argparse.ArgumentParser(description="拉取历史 PE 数据")
    parser.add_argument("--codes", help="股票代码列表, 逗号分隔 (如 000001.SZ,300750.SZ)")
    parser.add_argument("--pool", help="股票池名称 (如 default)")
    parser.add_argument("--force", action="store_true", help="强制重新拉取")
    args = parser.parse_args()

    # 获取股票列表
    if args.pool:
        from config.stock_pool_loader import load_pool
        pool = load_pool(args.pool)
        codes = [s["ts_code"] for s in pool["stocks"]]
    elif args.codes:
        codes = [c.strip() for c in args.codes.split(",")]
    else:
        # 默认用 default 池
        from config.stock_pool_loader import load_pool
        pool = load_pool("default")
        codes = [s["ts_code"] for s in pool["stocks"]]

    logger.info(f"准备拉取 {len(codes)} 只股票的 PE 数据: {codes}")
    logger.info("数据写入: quant.db: pe_history 表")

    pe_data = fetch_pe_batch(codes, force=args.force)

    # 打印摘要
    print("\n" + "=" * 60)
    print("PE 数据摘要")
    print("=" * 60)
    for ts_code, df in pe_data.items():
        if not df.empty:
            print(f"  {ts_code}: {len(df)} 行, "
                  f"区间 {df['trade_date'].iloc[0]} ~ {df['trade_date'].iloc[-1]}, "
                  f"PE 范围 {df['pe'].min():.1f} ~ {df['pe'].max():.1f}")


if __name__ == "__main__":
    main()
