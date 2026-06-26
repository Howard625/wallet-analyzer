"""Streamlit app: wallet transaction analyzer (DeBank-style)."""
from __future__ import annotations

from datetime import datetime, timedelta

import pandas as pd
import streamlit as st

from analyzer import (
    build_tx_dataframe,
    counterparty_summary,
    extract_token_transfers,
    filter_by_timeframe,
    token_summary,
)

st.set_page_config(page_title="Wallet Analyzer", layout="wide")
st.title("🔍 Wallet Transaction Analyzer")

# --- Sidebar inputs ---
with st.sidebar:
    st.header("Input")
    chain = st.selectbox("Chain", [
        "eth-mainnet", "bsc-mainnet", "base-mainnet",
        "arbitrum-mainnet", "optimism-mainnet", "polygon-mainnet",
        "avalanche-mainnet", "solana-mainnet",
    ], index=0)
    address = st.text_input("Wallet address or ENS", value="vitalik.eth")
    max_pages = st.number_input("Max pages (500 tx/page, empty=fetch all)", 0, 200, 5,
                                help="Start small to avoid rate limits. Empty = all history.")
    fetch_btn = st.button("Fetch & Analyze")

# --- Cached fetch ---
@st.cache_data(show_spinner="Fetching transactions...")
def load_data(chain, address, max_pages):
    df_tx = build_tx_dataframe(chain, address, max_pages=max_pages or None)
    df_transfers = extract_token_transfers(df_tx)
    return df_tx, df_transfers

if fetch_btn or "df_tx" in st.session_state:
    if fetch_btn:
        df_tx, df_transfers = load_data(chain, address, int(max_pages) or None)
        st.session_state["df_tx"] = df_tx
        st.session_state["df_transfers"] = df_transfers
        st.session_state["fetched_for"] = (chain, address)
    else:
        df_tx = st.session_state["df_tx"]
        df_transfers = st.session_state["df_transfers"]

    if df_tx.empty:
        st.warning("No transactions found for this address/chain.")
    else:
        st.success(f"Fetched **{len(df_tx)}** transactions, **{len(df_transfers)}** token transfers")

        # --- Timeframe filter ---
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            start_dt = st.date_input("From", df_tx["block_signed_at"].min().date())
        with col2:
            end_dt = st.date_input("To", df_tx["block_signed_at"].max().date())
        with col3:
            view = st.radio("View", ["Counterparties", "Tokens", "Raw transactions"], horizontal=True)

        start_ts = datetime.combine(start_dt, datetime.min.time(), tzinfo=df_tx["block_signed_at"].dt.tz)
        end_ts = datetime.combine(end_dt, datetime.max.time(), tzinfo=df_tx["block_signed_at"].dt.tz)

        tx_window = filter_by_timeframe(df_tx, start_ts, end_ts)
        tf_window = filter_by_timeframe(df_transfers, start_ts, end_ts)

        if view == "Counterparties":
            st.subheader("Top counterparties")
            summary = counterparty_summary(tf_window, address)
            if summary.empty:
                st.info("No token transfers in selected timeframe.")
            else:
                st.dataframe(summary, use_container_width=True)
                st.caption("Sorted by transaction count. Values in token units, not USD.")
        elif view == "Tokens":
            st.subheader("Token flows")
            summary = token_summary(tf_window, address)
            if summary.empty:
                st.info("No token transfers in selected timeframe.")
            else:
                st.dataframe(summary, use_container_width=True)
                st.caption("Net flow = inflow - outflow. Positive means you received more than sent.")
        else:
            st.subheader("Raw transactions")
            show_cols = ["block_signed_at", "from", "to", "value_eth", "gas_quote", "success", "tx_hash"]
            st.dataframe(tx_window[show_cols], use_container_width=True)
            st.caption(f"{len(tx_window)} txs in selected timeframe.")

        # --- Export ---
        st.divider()
        st.download_button(
            "Download token transfers as CSV",
            tf_window.to_csv(index=False),
            file_name=f"transfers_{address}_{chain}_{start_dt}_{end_dt}.csv",
            mime="text/csv",
        )
else:
    st.info("Enter a wallet address and click **Fetch & Analyze** to start.")
