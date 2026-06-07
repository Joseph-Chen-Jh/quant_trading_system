"""
Streamlit 监控面板
启动方式: streamlit run monitor/dashboard.py
"""
import sys
import os

# 确保项目根目录在 path 中
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pandas as pd
import streamlit as st
from simulation.account import VirtualAccount


def render_dashboard(account: VirtualAccount):
    """渲染监控面板"""

    st.set_page_config(page_title="量化交易监控", layout="wide")
    st.title("📊 量化交易系统 — 监控面板")

    summary = account.get_summary()

    # ---- 第一行: 核心指标 ----
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.metric("💰 总资产", f"¥{summary['total_asset']:,.0f}",
                  delta=f"{summary['total_return']*100:.2f}%")
    with col2:
        st.metric("💵 可用资金", f"¥{summary['available_cash']:,.0f}")
    with col3:
        st.metric("📦 持仓数", summary["position_count"])
    with col4:
        daily_ret = "—"
        if account.daily_nav:
            daily_ret = f"{account.daily_nav[-1]['return']*100:.2f}%"
        st.metric("📈 最新日收益", daily_ret)

    # ---- 净值曲线 ----
    st.subheader("📉 净值走势")
    if account.daily_nav:
        nav_df = pd.DataFrame(account.daily_nav)
        nav_df["date"] = pd.to_datetime(nav_df["date"])
        st.line_chart(nav_df.set_index("date")["nav"], use_container_width=True)

    # ---- 持仓明细 ----
    st.subheader("📋 当前持仓")
    if summary["positions"]:
        pos_df = pd.DataFrame(summary["positions"])
        pos_df["pnl_pct"] = pos_df["pnl_pct"].apply(lambda x: f"{x*100:.2f}%")
        pos_df["pnl"] = pos_df["pnl"].apply(lambda x: f"¥{x:,.0f}")
        pos_df["market_value"] = pos_df["market_value"].apply(lambda x: f"¥{x:,.0f}")
        pos_df["cost_price"] = pos_df["cost_price"].apply(lambda x: f"{x:.2f}")
        pos_df["current_price"] = pos_df["current_price"].apply(lambda x: f"{x:.2f}")
        st.dataframe(pos_df, use_container_width=True)
    else:
        st.info("暂无持仓")

    # ---- 最近交易 ----
    st.subheader("🔄 最近交易")
    if account.trade_history:
        trade_df = pd.DataFrame(account.trade_history[-30:])
        trade_df["time"] = trade_df["time"].astype(str)
        st.dataframe(trade_df, use_container_width=True)
    else:
        st.info("暂无交易记录")


# ---- 独立运行入口 ----
if __name__ == "__main__":
    account = VirtualAccount()
    render_dashboard(account)
