"""
量化交易策略分析面板 (Streamlit)

启动方式:
    streamlit run monitor/dashboard.py

功能:
    - 读取已生成的 backtest_nav.csv 和 backtest_trades.csv
    - 展示净值曲线对比、回撤曲线、交易买卖点、月度收益热力图
    - 关键指标卡片 + 交易明细表
"""
import os
import sys
import ssl

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# ---------- Windows SSL 证书库损坏的 workaround ----------
# tornado 启动时调用 ssl.create_default_context() 会读 Windows 证书存储,
# 某些第三方软件装了格式错误的根证书会导致 ASN1: NOT_ENOUGH_DATA 错误.
# 这里用 certifi 的 cacert.pem 替代 Windows 存储.
def _patch_ssl_context():
    try:
        import certifi
        cert_path = certifi.where()
        # 替换 create_default_context, 用 certifi 的证书
        _orig_create_default_context = ssl.create_default_context
        def _safe_create_default_context(purpose=ssl.Purpose.SERVER_AUTH, **kwargs):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.load_verify_locations(cafile=cert_path)
            ctx.check_hostname = kwargs.get("check_hostname", True)
            ctx.verify_mode = ssl.CERT_REQUIRED
            return ctx
        ssl.create_default_context = _safe_create_default_context
    except Exception:
        # 如果 certifi 没装或 patch 失败, 退化为不验证证书 (仅本地开发用)
        _orig_create_default_context = ssl.create_default_context
        def _no_verify_default_context(purpose=ssl.Purpose.SERVER_AUTH, **kwargs):
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            return ctx
        ssl.create_default_context = _no_verify_default_context

_patch_ssl_context()
# --------------------------------------------------------

import pandas as pd
import numpy as np
import streamlit as st
import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots

from monitor.report_viewer import load_report, find_default_report


def main():
    st.set_page_config(
        page_title="量化交易策略分析",
        page_icon="📊",
        layout="wide",
    )

    st.title("📊 量化交易策略分析")

    # ---------- 加载数据 ----------
    nav_path, trades_path = find_default_report()
    if not os.path.exists(nav_path) or not os.path.exists(trades_path):
        st.error("未找到回测结果文件, 请先运行: python main.py --mode backtest")
        st.info(f"期望路径:\n- {nav_path}\n- {trades_path}")
        return

    report = load_report(nav_path, trades_path)
    metrics = report.compute_metrics()

    if report.nav.empty:
        st.warning("净值表为空")
        return

    # ---------- 顶部: 数据源信息 + 刷新 ----------
    col_info, col_refresh = st.columns([4, 1])
    with col_info:
        st.caption(
            f"数据源: {os.path.basename(nav_path)} | "
            f"回测区间: {report.nav['date'].iloc[0]} ~ {report.nav['date'].iloc[-1]} | "
            f"交易日数: {metrics.get('n_days', 0)}"
        )
    with col_refresh:
        if st.button("🔄 刷新数据", help="重新读取 CSV 文件"):
            st.cache_data.clear()
            st.rerun()

    st.divider()

    # ---------- 关键指标卡片 ----------
    render_metric_cards(metrics)

    st.divider()

    # ---------- 控制开关 ----------
    col_opt1, col_opt2, col_opt3 = st.columns(3)
    with col_opt1:
        use_log = st.checkbox("净值曲线用对数刻度", value=False)
    with col_opt2:
        show_excess = st.checkbox("显示超额收益阴影", value=False)
    with col_opt3:
        show_benchmark = st.checkbox("显示沪深300基准", value=True)

    # ---------- 面板 1: 净值曲线对比 ----------
    st.subheader("📈 净值曲线对比")
    render_nav_chart(report, metrics, use_log, show_excess, show_benchmark)

    st.divider()

    # ---------- 面板 2: 回撤曲线 ----------
    st.subheader("📉 回撤曲线")
    render_drawdown_chart(report, metrics)

    st.divider()

    # ---------- 面板 3: 交易买卖点图 ----------
    st.subheader("🎯 交易买卖点")
    render_trade_points_chart(report)

    st.divider()

    # ---------- 面板 4: 月度收益热力图 + 交易明细表 ----------
    col_left, col_right = st.columns([3, 2])
    with col_left:
        st.subheader("📅 月度收益热力图")
        render_monthly_heatmap(metrics)
    with col_right:
        st.subheader("📋 交易明细")
        render_trade_table(report)

    st.divider()

    # ---------- 面板 5: 个股贡献分析 (多股票组合专用) ----------
    per_stock = report.get_per_stock_stats()
    if not per_stock.empty and len(per_stock) > 1:
        st.subheader("🏷️ 个股贡献分析")
        render_per_stock_section(report, per_stock)


def render_metric_cards(metrics: dict):
    """关键指标卡片"""
    col1, col2, col3, col4 = st.columns(4)

    with col1:
        ret = metrics.get("total_return", 0)
        bh_ret = metrics.get("buyhold_return", 0)
        delta = ret - bh_ret if bh_ret is not None else None
        st.metric(
            "策略累计收益",
            f"{ret:+.2%}",
            delta=f"vs 持有 {delta:+.2%}" if delta is not None else None,
            delta_color="inverse" if (delta is not None and delta < 0) else "normal",
        )

    with col2:
        mdd = metrics.get("max_drawdown", 0)
        bh_mdd = metrics.get("buyhold_max_dd", 0)
        delta = mdd - bh_mdd if bh_mdd is not None else None
        st.metric(
            "最大回撤",
            f"{mdd:.2%}",
            delta=f"vs 持有 {bh_mdd:.2%}" if bh_mdd is not None else None,
            delta_color="normal",  # 回撤更小是好事, 但数值更负, 这里不反转
        )

    with col3:
        sharpe = metrics.get("sharpe", 0)
        bh_sharpe = metrics.get("buyhold_sharpe", 0)
        delta = sharpe - bh_sharpe if bh_sharpe is not None else None
        st.metric(
            "夏普比率",
            f"{sharpe:.3f}",
            delta=f"vs 持有 {bh_sharpe:.3f}" if bh_sharpe is not None else None,
            delta_color="inverse" if (delta is not None and delta < 0) else "normal",
        )

    with col4:
        win_rate = metrics.get("win_rate", 0)
        pl_ratio = metrics.get("profit_loss_ratio", 0)
        st.metric(
            "胜率 / 盈亏比",
            f"{win_rate:.1%} / {pl_ratio:.2f}",
            delta=f"{metrics.get('n_trades', 0)} 笔交易",
            delta_color="off",
        )


def render_nav_chart(report, metrics, use_log, show_excess, show_benchmark):
    """净值曲线对比图"""
    nav = report.nav
    fig = go.Figure()

    # 策略净值
    fig.add_trace(go.Scatter(
        x=nav["date"], y=nav["nav"] / nav["nav"].iloc[0],
        name="策略", line=dict(color="royalblue", width=2),
        hovertemplate="日期: %{x}<br>净值: %{y:.4f}<extra></extra>",
    ))

    # 买入持有
    if "buyhold_nav" in nav.columns:
        fig.add_trace(go.Scatter(
            x=nav["date"], y=nav["buyhold_nav"],
            name="买入持有", line=dict(color="orange", width=2),
            hovertemplate="日期: %{x}<br>净值: %{y:.4f}<extra></extra>",
        ))

    # 沪深300
    if show_benchmark and "benchmark_nav" in nav.columns:
        bench = nav.dropna(subset=["benchmark_nav"])
        if not bench.empty:
            fig.add_trace(go.Scatter(
                x=bench["date"], y=bench["benchmark_nav"],
                name="沪深300", line=dict(color="green", width=1.5, dash="dash"),
                hovertemplate="日期: %{x}<br>净值: %{y:.4f}<extra></extra>",
            ))

    # 超额收益阴影 (策略 - 买入持有)
    if show_excess and "buyhold_nav" in nav.columns:
        excess = nav["nav"] / nav["nav"].iloc[0] - nav["buyhold_nav"]
        fig.add_trace(go.Scatter(
            x=nav["date"], y=excess,
            name="超额收益", fill="tozeroy", fillcolor="rgba(255,0,0,0.1)",
            line=dict(color="rgba(255,0,0,0.3)", width=1),
            hovertemplate="日期: %{x}<br>超额: %{y:.4f}<extra></extra>",
        ))

    fig.update_layout(
        xaxis_title="日期", yaxis_title="归一化净值 (首日=1.0)",
        yaxis_type="log" if use_log else "linear",
        hovermode="x unified", height=450,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_drawdown_chart(report, metrics):
    """回撤曲线图"""
    nav = report.nav
    fig = go.Figure()

    # 策略回撤
    strat_dd = report.get_drawdown_series()
    fig.add_trace(go.Scatter(
        x=nav["date"], y=strat_dd,
        name="策略回撤", fill="tozeroy", fillcolor="rgba(70,130,180,0.3)",
        line=dict(color="royalblue", width=1.5),
        hovertemplate="日期: %{x}<br>回撤: %{y:.2%}<extra></extra>",
    ))

    # 买入持有回撤
    bh_dd = report.get_buyhold_drawdown_series()
    if bh_dd is not None:
        fig.add_trace(go.Scatter(
            x=nav["date"], y=bh_dd,
            name="买入持有回撤", fill="tozeroy", fillcolor="rgba(255,165,0,0.2)",
            line=dict(color="orange", width=1.5),
            hovertemplate="日期: %{x}<br>回撤: %{y:.2%}<extra></extra>",
        ))

    # 标注策略最大回撤点
    max_dd = metrics.get("max_drawdown", 0)
    max_dd_date = metrics.get("max_dd_date")
    if max_dd_date:
        fig.add_annotation(
            x=str(max_dd_date), y=max_dd,
            text=f"最大回撤 {max_dd:.2%}",
            showarrow=True, arrowhead=2,
            font=dict(color="red", size=12),
            ax=20, ay=-30,
        )

    fig.update_layout(
        xaxis_title="日期", yaxis_title="回撤幅度",
        yaxis_tickformat=".0%",
        hovermode="x unified", height=350,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_trade_points_chart(report):
    """交易买卖点图"""
    nav = report.nav
    trades = report.trades

    if trades.empty:
        st.info("无交易记录")
        return

    fig = go.Figure()

    # 股价折线 (用 buyhold_close 或从 nav 推算)
    if "buyhold_close" in nav.columns:
        price = nav["buyhold_close"]
        price_normalized = nav["buyhold_close"] * nav["nav"].iloc[0] / nav["buyhold_close"].iloc[0]
    else:
        price_normalized = nav["nav"]

    fig.add_trace(go.Scatter(
        x=nav["date"], y=price_normalized,
        name="股价", line=dict(color="gray", width=1),
        hovertemplate="日期: %{x}<br>价格: %{y:.2f}<extra></extra>",
    ))

    # 买卖点
    if "trade_date" in trades.columns and "direction" in trades.columns:
        # 把 trade_date 转为字符串与 nav["date"] 对齐
        trades = trades.copy()
        trades["date_str"] = trades["trade_date"].astype(str)

        buys = trades[trades["direction"] == "BUY"]
        sells = trades[trades["direction"] == "SELL"]

        # 价格查找表
        price_map = dict(zip(nav["date"].astype(str), price_normalized))

        # BUY 点
        buy_prices = [price_map.get(d, None) for d in buys["date_str"]]
        buy_valid = buys[[p is not None for p in buy_prices]]
        buy_prices_valid = [p for p in buy_prices if p is not None]

        if not buy_valid.empty:
            fig.add_trace(go.Scatter(
                x=buy_valid["date_str"], y=buy_prices_valid,
                mode="markers", name="买入",
                marker=dict(symbol="triangle-up", size=12, color="green"),
                hovertemplate="日期: %{x}<br>买入价: %{y:.2f}<extra></extra>",
            ))

        # SELL 点, 颜色按盈亏
        sell_prices = [price_map.get(d, None) for d in sells["date_str"]]
        sell_valid_mask = [p is not None for p in sell_prices]
        sell_valid = sells[sell_valid_mask]
        sell_prices_valid = [p for p in sell_prices if p is not None]

        if not sell_valid.empty:
            colors = ["red" if (pd.notna(p) and p > 0) else "darkred"
                      for p in sell_valid.get("pnl", [])]
            fig.add_trace(go.Scatter(
                x=sell_valid["date_str"], y=sell_prices_valid,
                mode="markers", name="卖出",
                marker=dict(symbol="triangle-down", size=12, color=colors),
                hovertemplate="日期: %{x}<br>卖出价: %{y:.2f}<br>盈亏: %{customdata}<extra></extra>",
                customdata=[f"{p:,.0f}" if pd.notna(p) else "-" for p in sell_valid.get("pnl", [])],
            ))

    fig.update_layout(
        xaxis_title="日期", yaxis_title="价格",
        hovermode="x unified", height=450,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_monthly_heatmap(metrics: dict):
    """月度收益热力图"""
    monthly = metrics.get("monthly_returns")
    if monthly is None or monthly.empty:
        st.info("无月度收益数据")
        return

    # 重命名列
    monthly_display = monthly.copy()
    monthly_display.columns = [
        c if c == "全年" else f"{c}月" for c in monthly_display.columns
    ]
    monthly_display.index.name = "年份"

    # 转百分比
    monthly_pct = (monthly_display * 100).round(2)

    fig = px.imshow(
        monthly_pct,
        color_continuous_scale=["green", "white", "red"],
        color_continuous_midpoint=0,
        text_auto=".2f",
        aspect="auto",
    )
    fig.update_layout(
        height=300,
        xaxis_title="月份", yaxis_title="年份",
        coloraxis_colorbar=dict(title="收益(%)"),
    )
    st.plotly_chart(fig, use_container_width=True)


def render_trade_table(report):
    """交易明细表"""
    if report.trades.empty:
        st.info("无交易记录")
        return

    trades = report.trades.copy()

    # 筛选
    filter_opt = st.radio(
        "筛选", ["全部", "仅盈利", "仅亏损"],
        horizontal=True, key="trade_filter",
    )
    if "pnl" in trades.columns and "direction" in trades.columns:
        sells = trades[trades["direction"] == "SELL"].copy()
        if filter_opt == "仅盈利":
            show = sells[sells["pnl"] > 0]
        elif filter_opt == "仅亏损":
            show = sells[sells["pnl"] <= 0]
        else:
            show = trades
    else:
        show = trades

    # 格式化显示
    display_cols = [c for c in [
        "trade_date", "direction", "ts_code", "price", "volume",
        "commission", "stamp_tax", "pnl"
    ] if c in show.columns]

    show = show[display_cols].copy()
    if "pnl" in show.columns:
        show["pnl"] = show["pnl"].apply(lambda x: f"{x:,.0f}" if pd.notna(x) else "-")
    if "price" in show.columns:
        show["price"] = show["price"].apply(lambda x: f"{x:.2f}")
    if "commission" in show.columns:
        show["commission"] = show["commission"].apply(lambda x: f"{x:.2f}")
    if "stamp_tax" in show.columns:
        show["stamp_tax"] = show["stamp_tax"].apply(lambda x: f"{x:.2f}")

    # 重命名
    rename_map = {
        "trade_date": "日期", "direction": "方向", "ts_code": "代码",
        "price": "价格", "volume": "数量", "commission": "佣金",
        "stamp_tax": "印花税", "pnl": "盈亏",
    }
    show = show.rename(columns={k: v for k, v in rename_map.items() if k in show.columns})

    st.dataframe(show, use_container_width=True, hide_index=True)

    # 汇总
    if "pnl" in trades.columns and "direction" in trades.columns:
        sells = trades[trades["direction"] == "SELL"]
        total_pnl = sells["pnl"].sum()
        st.metric("总盈亏 (卖出合计)", f"¥{total_pnl:,.0f}")


def render_per_stock_section(report, per_stock: pd.DataFrame):
    """个股贡献分析板块 (多股票组合专用)"""

    # ---------- 子面板 A: 个股盈亏柱状图 ----------
    st.markdown("**个股盈亏贡献**")
    fig_bar = go.Figure()
    # 按总盈亏排序 (per_stock 已排序)
    colors = ["#d62728" if p < 0 else "#2ca02c" for p in per_stock["总盈亏"]]
    fig_bar.add_trace(go.Bar(
        x=per_stock["ts_code"],
        y=per_stock["总盈亏"],
        marker_color=colors,
        text=[f"{v:,.0f}" for v in per_stock["总盈亏"]],
        textposition="outside",
        hovertemplate="代码: %{x}<br>总盈亏: ¥%{y:,.0f}<extra></extra>",
    ))
    fig_bar.update_layout(
        xaxis_title="股票代码", yaxis_title="已实现盈亏 (¥)",
        height=350, showlegend=False,
        margin=dict(t=20, b=20),
    )
    st.plotly_chart(fig_bar, use_container_width=True)

    # ---------- 子面板 B: 个股统计表 ----------
    st.markdown("**个股交易统计**")
    display = per_stock.copy()
    # 格式化
    display["胜率"] = display["胜率"].apply(lambda x: f"{x:.1%}")
    display["总盈亏"] = display["总盈亏"].apply(lambda x: f"¥{x:,.0f}")
    display["总手续费"] = display["总手续费"].apply(lambda x: f"¥{x:,.0f}")
    display["净盈亏"] = display["净盈亏"].apply(lambda x: f"¥{x:,.0f}")
    display["平均持有天数"] = display["平均持有天数"].apply(lambda x: f"{x:.1f}")
    display = display.rename(columns={"ts_code": "代码"})
    st.dataframe(display, use_container_width=True, hide_index=True)

    # ---------- 子面板 C: 个股月度盈亏热力图 ----------
    monthly_pnl = report.get_per_stock_monthly_pnl()
    if not monthly_pnl.empty:
        st.markdown("**个股月度已实现盈亏 (热力图)**")
        # 转为万元显示, 保留 2 位
        monthly_display = (monthly_pnl / 10000).round(2)

        fig_heat = px.imshow(
            monthly_display,
            color_continuous_scale=["#2ca02c", "white", "#d62728"],
            color_continuous_midpoint=0,
            text_auto=".2f",
            aspect="auto",
        )
        fig_heat.update_layout(
            height=max(250, len(monthly_display) * 30),
            xaxis_title="股票代码", yaxis_title="年月",
            coloraxis_colorbar=dict(title="盈亏(万)"),
            margin=dict(t=20, b=20),
        )
        st.plotly_chart(fig_heat, use_container_width=True)


if __name__ == "__main__":
    main()
