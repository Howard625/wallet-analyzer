"""Streamlit app: wallet transaction analyzer (DeBank-style)."""
from __future__ import annotations

import re
from datetime import datetime

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from analyzer import (
    build_multi_chain_tx,
    build_swap_summaries,
    build_tx_dataframe,
    extract_transfers,
    fetch_token_prices,
    filter_by_entity,
    filter_by_timeframe,
    get_first_fund,
    unified_ranking,
)
from labels import label_or_short

# --- Page config ---
st.set_page_config(
    page_title="Wallet Analyzer",
    page_icon="🔍",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown("""
<style>
    .stApp {
        background-color: #ffffff;
    }
    div[data-testid="stButton"] > button {
        background-color: #f8f9fa;
        border: 1px solid #e8eaed;
        border-radius: 8px;
        color: #1a1a1a;
        font-size: 13px;
        padding: 10px 8px;
        text-align: left;
        white-space: pre-line;
        line-height: 1.5;
        height: auto;
    }
    div[data-testid="stButton"] > button:hover {
        border-color: #1a73e8;
        background-color: #e8f0fe;
    }
</style>
""", unsafe_allow_html=True)

ALL_CHAINS = [
    "eth-mainnet", "bsc-mainnet", "base-mainnet",
    "arbitrum-mainnet", "optimism-mainnet", "polygon-mainnet",
    "avalanche-mainnet", "solana-mainnet",
]

CHAIN_COLORS = {
    "eth-mainnet": "#627EEA",
    "bsc-mainnet": "#F3BA2F",
    "base-mainnet": "#0052FF",
    "arbitrum-mainnet": "#28A0F0",
    "optimism-mainnet": "#FF0420",
    "polygon-mainnet": "#8247E5",
    "avalanche-mainnet": "#E84142",
    "solana-mainnet": "#9945FF",
}

CHAIN_NATIVE = {
    "eth-mainnet": "ETH",
    "bsc-mainnet": "BNB",
    "base-mainnet": "ETH",
    "arbitrum-mainnet": "ETH",
    "optimism-mainnet": "ETH",
    "polygon-mainnet": "MATIC",
    "avalanche-mainnet": "AVAX",
}

CHAIN_EXPLORER = {
    "eth-mainnet": "https://etherscan.io/tx/",
    "bsc-mainnet": "https://bscscan.com/tx/",
    "base-mainnet": "https://basescan.org/tx/",
    "arbitrum-mainnet": "https://arbiscan.io/tx/",
    "optimism-mainnet": "https://optimistic.etherscan.io/tx/",
    "polygon-mainnet": "https://polygonscan.com/tx/",
    "avalanche-mainnet": "https://snowtrace.io/tx/",
}


def _parse_swap_tokens(swap_str: str) -> list[tuple[str, float]]:
    """Parse a swap string like '4,245.0000 O ($1,234) + 75,569.0000 USDT ($75,569)' into [(symbol, amount), ...]."""
    if not swap_str or swap_str == "—":
        return []
    results = []
    # Split by " + "
    parts = swap_str.split(" + ")
    for part in parts:
        part = part.strip()
        # Match "number symbol" — symbol is just alphanumeric chars (no parentheses)
        m = re.match(r"([\d,.]+)\s+([A-Za-z0-9]+)", part)
        if m:
            amount_str = m.group(1).replace(",", "")
            symbol = m.group(2).strip()
            try:
                amount = float(amount_str)
                results.append((symbol, amount))
            except ValueError:
                pass
    return results


def _token_in_swap(swap_str: str, token_symbol: str) -> bool:
    """Check if a specific token symbol appears in the swap string (exact match)."""
    tokens = _parse_swap_tokens(swap_str)
    return any(sym.upper() == token_symbol.upper() for sym, _ in tokens)


# --- Sidebar inputs ---
with st.sidebar:
    st.header("⚙️ Input")
    selected_chains = st.multiselect(
        "Chains",
        ALL_CHAINS,
        default=["eth-mainnet", "bsc-mainnet"],
    )
    # Check if there's a pending address from First Fund trace
    pending = st.session_state.get("pending_address", "")
    address = st.text_input("Wallet address or ENS", value=pending or "vitalik.eth")
    if pending:
        # Clear the pending flag after using it
        st.session_state.pop("pending_address", None)
    max_pages = st.number_input("Max pages per chain (0=all)", 0, 200, 5,
                                help="500 tx/page. Start small to avoid rate limits.")
    fetch_btn = st.button("🚀 Fetch & Analyze", use_container_width=True)
    st.divider()
    st.caption("💡 Tip: Use 2-3 pages for quick test, 0 for full history")


@st.cache_data(show_spinner="Fetching transactions...")
def load_data(chains_tuple, address, max_pages):
    chains = list(chains_tuple)
    df_tx, resolved = build_multi_chain_tx(chains, address, max_pages=max_pages or None)
    contracts = set()
    for _, tx in df_tx.iterrows():
        for log in tx["log_events"]:
            decoded = log.get("decoded")
            if decoded and decoded.get("name") == "Transfer":
                addr = log.get("sender_address")
                if addr:
                    contracts.add(addr)
    prices = fetch_token_prices(contracts, chains)
    df_transfers = extract_transfers(df_tx, resolved, prices)
    return df_tx, df_transfers, resolved


# --- Session state init ---
if "drill_entity" not in st.session_state:
    st.session_state["drill_entity"] = None
    st.session_state["drill_type"] = None

if fetch_btn or "df_tx" in st.session_state:
    if fetch_btn:
        if not selected_chains:
            st.warning("Please select at least one chain.")
            st.stop()
        df_tx, df_transfers, resolved_addr = load_data(
            tuple(selected_chains), address, int(max_pages) or None
        )
        st.session_state["df_tx"] = df_tx
        st.session_state["df_transfers"] = df_transfers
        st.session_state["resolved_addr"] = resolved_addr
        st.session_state["drill_entity"] = None
        st.session_state["drill_type"] = None
        st.session_state["show_trace"] = False
    else:
        df_tx = st.session_state["df_tx"]
        df_transfers = st.session_state["df_transfers"]
        resolved_addr = st.session_state.get("resolved_addr", address)

    if df_tx.empty:
        st.warning("No transactions found for this address/chain combination.")
    else:
        chain_counts = df_tx.groupby("chain").size()
        total_usd_in = df_transfers[df_transfers["direction"] == "in"]["value_usd"].sum() if not df_transfers.empty else 0
        total_usd_out = df_transfers[df_transfers["direction"] == "out"]["value_usd"].sum() if not df_transfers.empty else 0

        m1, m2, m3, m4 = st.columns(4)
        with m1:
            st.metric("Transactions", len(df_tx))
        with m2:
            st.metric("Transfers", len(df_transfers))
        with m3:
            st.metric("USD In", f"${total_usd_in:,.0f}")
        with m4:
            st.metric("USD Out", f"${total_usd_out:,.0f}")

        # --- First Fund ---
        first_fund = get_first_fund(df_tx, df_transfers, resolved_addr)
        if first_fund:
            ff_from = first_fund["from"] or ""
            ff_label = first_fund["from_label"] or label_or_short(ff_from)
            ff_chain = first_fund["chain"]
            native_sym = CHAIN_NATIVE.get(ff_chain, "ETH")
            
            with st.expander(f"🟢 First Fund: {first_fund['timestamp'].strftime('%Y-%m-%d %H:%M:%S')} — from {ff_label}", expanded=True):
                fc1, fc2, fc3, fc4 = st.columns(4)
                with fc1:
                    st.metric("Date", first_fund["timestamp"].strftime("%Y-%m-%d"))
                with fc2:
                    st.metric("From", ff_label[:20] if ff_label else ff_from[:20])
                with fc3:
                    # Show token info if ERC20, otherwise native
                    if first_fund.get("token_symbol") and first_fund.get("amount", 0) > 0:
                        st.metric("Value", f"{first_fund['amount']:,.4f} {first_fund['token_symbol']}")
                    else:
                        st.metric("Value", f"{first_fund['value_eth']:.4f} {native_sym}")
                with fc4:
                    st.metric("USD", f"${first_fund['value_quote']:.2f}")
                
                st.caption(f"Address: `{ff_from}`")
                
                # tx hash link
                ff_explorer = CHAIN_EXPLORER.get(ff_chain, "")
                if ff_explorer:
                    st.caption(f"tx: [{first_fund['tx_hash'][:30]}...]({ff_explorer}{first_fund['tx_hash']}) | chain: {ff_chain}")
                else:
                    st.caption(f"tx: {first_fund['tx_hash'][:30]}... | chain: {ff_chain}")
                
                # Button to trace fund chain (manual, not auto)
                if st.button("🔗 Trace Fund Chain"):
                    st.session_state["show_trace"] = True
                
                if st.session_state.get("show_trace", False):
                    with st.spinner("Tracing fund origin..."):
                        current_addr = ff_from
                        current_chain = ff_chain
                        for depth in range(5):
                            try:
                                prev_df, _ = build_tx_dataframe(current_chain, current_addr, max_pages=2)
                                prev_ff = get_first_fund(prev_df)
                                if not prev_ff or prev_ff["from"] == current_addr:
                                    break
                                
                                prev_label = prev_ff["from_label"] or label_or_short(prev_ff["from"])
                                prev_native = CHAIN_NATIVE.get(prev_ff["chain"], "ETH")
                                
                                # Check if it's an exchange
                                lbl_lower = prev_ff["from_label"].lower() if prev_ff["from_label"] else ""
                                exchange_keywords = ["exchange", "binance", "okx", "coinbase", "kraken", "hot", "deposit", "mexc", "bybit", "gate", "kucoin", "htx", "bitget", "upbit", "bitfinex", "withdrawal", "cold"]
                                is_exchange = any(x in lbl_lower for x in exchange_keywords)
                                
                                indent = "  " * (depth + 1)
                                icon = "🏦" if is_exchange else "➡️"
                                st.markdown(f"{indent}{icon} {prev_ff['timestamp'].strftime('%Y-%m-%d')} **{prev_label}** sent {prev_ff['value_eth']:.4f} {prev_native} (${prev_ff['value_quote']:.2f}) to `{prev_ff['from'][:20]}...`")
                                
                                if is_exchange:
                                    st.markdown(f"{indent}✅ **Found exchange origin: {prev_label}**")
                                    break
                                
                                current_addr = prev_ff["from"]
                                current_chain = prev_ff["chain"]
                            except Exception as e:
                                st.caption(f"Trace stopped: {e}")
                                break
                        else:
                            st.caption("Max depth reached (5 levels)")
                
                # Button to search this address in our product
                if st.button(f"🔍 Analyze {ff_from[:10]}... in this tool"):
                    st.session_state["pending_address"] = ff_from
                    st.rerun()

        # --- Timeframe filter ---
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            start_dt = st.date_input("From", df_tx["block_signed_at"].min().date())
        with col2:
            end_dt = st.date_input("To", df_tx["block_signed_at"].max().date())
        with col3:
            mode = st.radio("Mode", ["📊 Analysis", "📋 Transactions"], horizontal=True)

        start_ts = pd.Timestamp(datetime.combine(start_dt, datetime.min.time()))
        end_ts = pd.Timestamp(datetime.combine(end_dt, datetime.max.time()))
        if start_ts.tzinfo is None:
            start_ts = start_ts.tz_localize(df_tx["block_signed_at"].dt.tz or "UTC")
        if end_ts.tzinfo is None:
            end_ts = end_ts.tz_localize(df_tx["block_signed_at"].dt.tz or "UTC")

        tx_window = filter_by_timeframe(df_tx, start_ts.to_pydatetime(), end_ts.to_pydatetime())
        tf_window = filter_by_timeframe(df_transfers, start_ts.to_pydatetime(), end_ts.to_pydatetime())

        # Pre-compute swap summaries for the window
        swaps_all = build_swap_summaries(tx_window, resolved_addr, tf_window)
        swap_lookup = {}
        if not swaps_all.empty:
            for _, s in swaps_all.iterrows():
                swap_lookup[s["tx_hash"]] = s

        # --- Handle drill-down ---
        if st.session_state["drill_entity"]:
            if st.button("← Back"):
                st.session_state["drill_entity"] = None
                st.session_state["drill_type"] = None
                st.rerun()

            entity_name = st.session_state['drill_entity']
            etype = st.session_state['drill_type']
            st.subheader(f"📊 {entity_name}")

            drilled = filter_by_entity(
                tf_window, resolved_addr,
                entity_name,
                etype,
            )

            if drilled.empty:
                st.info(f"No transfers found for {entity_name} in the selected timeframe. Try adjusting the date range or click ← Back.")
            else:
                if etype == "token":
                    # Filter swaps that involve this token (exact symbol match)
                    token_swaps = swaps_all[
                        swaps_all["spent"].apply(lambda s: _token_in_swap(s, entity_name)) |
                        swaps_all["received"].apply(lambda s: _token_in_swap(s, entity_name))
                    ] if not swaps_all.empty else pd.DataFrame()

                    if not token_swaps.empty:
                        st.caption(f"{len(token_swaps)} swaps involving {entity_name}")

                        for _, swap in token_swaps.iterrows():
                            time_str = swap["block_signed_at"].strftime("%Y-%m-%d %H:%M:%S")
                            chain_tag = swap["chain"]
                            dex_name = swap["dex"]

                            # Parse and format spent/received
                            spent_tokens = _parse_swap_tokens(swap["spent"]) if swap["spent"] else []
                            received_tokens = _parse_swap_tokens(swap["received"]) if swap["received"] else []

                            c1, c2, c3 = st.columns([2, 5, 2])
                            with c1:
                                st.write(f"🕐 {time_str}")
                                st.caption(f"{chain_tag} | {dex_name}")
                            with c2:
                                # Swap strings now include USD directly from build_swap_summaries
                                if swap["spent"]:
                                    st.write(f"🔴 -{swap['spent']}")
                                if swap["received"]:
                                    st.write(f"🟢 +{swap['received']}")
                            with c3:
                                explorer_url = CHAIN_EXPLORER.get(chain_tag, "")
                                if explorer_url:
                                    st.markdown(f"[tx: {swap['tx_hash'][:10]}...]({explorer_url}{swap['tx_hash']})")
                                else:
                                    st.caption(f"tx: {swap['tx_hash'][:18]}...")

                            st.markdown("---")

                    # Also show non-swap transfers involving this token
                    non_swap_drilled = drilled[~drilled["tx_hash"].isin(swap_lookup.keys())]
                    if not non_swap_drilled.empty:
                        with st.expander(f"📋 Other transfers ({len(non_swap_drilled)})"):
                            nd = non_swap_drilled.copy()
                            nd["from_label"] = nd["from"].apply(label_or_short)
                            nd["to_label"] = nd["to"].apply(label_or_short)
                            st.dataframe(
                                nd[["block_signed_at", "from_label", "to_label", "token_symbol", "direction", "amount", "value_usd", "chain", "tx_hash"]],
                                use_container_width=True,
                                column_config={
                                    "value_usd": st.column_config.NumberColumn(format="$%.2f"),
                                    "amount": st.column_config.NumberColumn(format="%.4f"),
                                    "block_signed_at": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                                },
                            )
                else:
                    # Address drill-down
                    drilled_display = drilled.copy()
                    drilled_display["from_label"] = drilled_display["from"].apply(label_or_short)
                    drilled_display["to_label"] = drilled_display["to"].apply(label_or_short)
                    st.dataframe(
                        drilled_display[["block_signed_at", "from_label", "to_label", "token_symbol", "direction", "amount", "value_usd", "chain", "tx_hash"]],
                        use_container_width=True,
                        column_config={
                            "value_usd": st.column_config.NumberColumn(format="$%.2f"),
                            "amount": st.column_config.NumberColumn(format="%.4f"),
                            "block_signed_at": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                        },
                    )
                    st.caption(f"{len(drilled)} transfers")

        elif mode.startswith("📊"):
            # --- Analysis Mode ---
            st.subheader("Analysis — Top 20")
            ranking = unified_ranking(tf_window, resolved_addr)

            if ranking.empty:
                st.info("No transfers in selected timeframe.")
            else:
                # --- Charts row ---
                col_a, col_b = st.columns(2)
                with col_a:
                    token_ranking = ranking[ranking["entity_type"] == "token"].head(10)
                    if not token_ranking.empty:
                        fig_pie = px.pie(
                            token_ranking, values="total_usd", names="display_name",
                            title="Token Distribution (by USD)",
                            color_discrete_sequence=px.colors.qualitative.Set3,
                        )
                        fig_pie.update_layout(
                            height=350, margin=dict(l=20, r=20, t=40, b=20),
                            paper_bgcolor="#ffffff", font_color="#1a1a1a",
                        )
                        st.plotly_chart(fig_pie, use_container_width=True)

                with col_b:
                    if not tf_window.empty:
                        daily_flow = tf_window.copy()
                        daily_flow["date"] = daily_flow["block_signed_at"].dt.date
                        flow_pivot = daily_flow.groupby(["date", "direction"])["value_usd"].sum().unstack(fill_value=0)
                        if "in" not in flow_pivot.columns:
                            flow_pivot["in"] = 0
                        if "out" not in flow_pivot.columns:
                            flow_pivot["out"] = 0
                        fig_flow = go.Figure()
                        fig_flow.add_trace(go.Bar(x=flow_pivot.index, y=flow_pivot["in"], name="In", marker_color="#188038"))
                        fig_flow.add_trace(go.Bar(x=flow_pivot.index, y=-flow_pivot["out"], name="Out", marker_color="#d93025"))
                        fig_flow.update_layout(
                            title="USD Flow Over Time",
                            barmode="relative",
                            height=350,
                            margin=dict(l=20, r=20, t=40, b=20),
                            showlegend=True,
                            paper_bgcolor="#ffffff", font_color="#1a1a1a",
                        )
                        st.plotly_chart(fig_flow, use_container_width=True)

                # --- Top 20 cards ---
                st.divider()
                top20 = ranking.head(20)
                cols_per_row = 4
                for i in range(0, len(top20), cols_per_row):
                    row_data = top20.iloc[i:i + cols_per_row]
                    cols = st.columns(cols_per_row)
                    for j, (_, row) in enumerate(row_data.iterrows()):
                        with cols[j]:
                            entity = row["entity"]
                            etype = row["entity_type"]
                            tx_count = int(row["tx_count"])
                            in_count = int(row["in_count"])
                            out_count = int(row["out_count"])
                            usd = row["total_usd"]
                            token_amt = row.get("token_amount", "")
                            display_name = row.get("display_name", entity)

                            icon = "🏦" if etype == "address" else "🪙"
                            usd_str = f"${usd:,.0f}" if usd > 0 else "—"
                            amt_str = f"{float(token_amt):,.2f}" if token_amt and token_amt != "" else ""
                            line2 = f"{tx_count} txs (↑{in_count} ↓{out_count}) | {usd_str}"
                            if amt_str:
                                line2 += f" | {amt_str}"

                            if st.button(
                                f"{icon} {display_name}\n{line2}",
                                key=f"card_{i}_{j}",
                                use_container_width=True,
                            ):
                                st.session_state["drill_entity"] = entity
                                st.session_state["drill_type"] = etype
                                st.rerun()

                # Full ranking table
                st.divider()
                with st.expander("📋 Full ranking table"):
                    st.dataframe(ranking, use_container_width=True, column_config={
                        "total_usd": st.column_config.NumberColumn(format="$%.2f"),
                        "first_seen": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                        "last_seen": st.column_config.DatetimeColumn(format="YYYY-MM-DD"),
                    })

                # Chain distribution chart
                if len(chain_counts) > 1:
                    fig_chain = px.pie(
                        values=chain_counts.values, names=chain_counts.index,
                        title="Transactions by Chain",
                        color=chain_counts.index,
                        color_discrete_map={k: CHAIN_COLORS.get(k, "#888") for k in chain_counts.index},
                    )
                    fig_chain.update_layout(
                        height=300, margin=dict(l=20, r=20, t=40, b=20),
                        paper_bgcolor="#ffffff", font_color="#1a1a1a",
                    )
                    st.plotly_chart(fig_chain, use_container_width=True)

                # --- All Transactions (DeBank style) ---
                st.divider()
                st.subheader("📋 All Transactions")

                display_count = min(100, len(tx_window))
                for _, tx in tx_window.head(display_count).iterrows():
                    time_str = tx["block_signed_at"].strftime("%Y-%m-%d %H:%M:%S")
                    from_lbl = label_or_short(tx["from"])
                    to_lbl = label_or_short(tx["to"])
                    native_sym = CHAIN_NATIVE.get(tx["chain"], "ETH")
                    chain_color = CHAIN_COLORS.get(tx["chain"], "#888")
                    explorer_url = CHAIN_EXPLORER.get(tx["chain"], "")
                    tx_hash = tx["tx_hash"]
                    tx_link = f"[{tx_hash[:10]}...]({explorer_url}{tx_hash})"

                    col_time, col_main, col_gas = st.columns([2, 6, 2])

                    with col_time:
                        st.write(f"🕐 {time_str}")
                        st.markdown(
                            f"<span style='color:{chain_color};font-size:11px'>● {tx['chain'].split('-')[0].upper()}</span>",
                            unsafe_allow_html=True,
                        )

                    with col_main:
                        if tx_hash in swap_lookup:
                            swap = swap_lookup[tx_hash]
                            st.markdown(
                                f"**Swap** <span style='color:#999;font-size:12px'>via {swap['dex']}</span>",
                                unsafe_allow_html=True,
                            )
                            if swap["spent"]:
                                st.write(f"🔴 -{swap['spent']}")
                            if swap["received"]:
                                st.write(f"🟢 +{swap['received']}")
                            st.caption(f"tx: {tx_link}")
                        else:
                            # Non-swap tx — show ERC20 transfers and approvals with counterparty
                            tx_transfers = tf_window[tf_window["tx_hash"] == tx_hash]
                            
                            if not tx_transfers.empty:
                                outs = tx_transfers[(tx_transfers["direction"] == "out") & (tx_transfers["amount"] > 0)]
                                ins = tx_transfers[(tx_transfers["direction"] == "in") & (tx_transfers["amount"] > 0)]
                                
                                if not outs.empty:
                                    for _, t in outs.iterrows():
                                        usd_str = f" (${t['value_usd']:,.2f})" if t["value_usd"] > 0 else ""
                                        to_label = label_or_short(t["to"]) if t["to"] else ""
                                        st.write(f"🔴 -{t['amount']:,.4f} {t['token_symbol']}{usd_str} → {to_label}")
                                if not ins.empty:
                                    for _, t in ins.iterrows():
                                        usd_str = f" (${t['value_usd']:,.2f})" if t["value_usd"] > 0 else ""
                                        from_label_t = label_or_short(t["from"]) if t["from"] else ""
                                        st.write(f"🟢 +{t['amount']:,.4f} {t['token_symbol']}{usd_str} ← {from_label_t}")
                            else:
                                # Check for Approval events
                                has_approval = False
                                for log in tx["log_events"]:
                                    decoded = log.get("decoded")
                                    if decoded and decoded.get("name") == "Approval":
                                        has_approval = True
                                        params = {}
                                        for p in (decoded.get("params") or []):
                                            if p.get("name") and p.get("value") is not None:
                                                params[p["name"]] = p["value"]
                                        token_sym = log.get("sender_contract_ticker_symbol") or ""
                                        spender = params.get("spender", "")
                                        spender_label = label_or_short(spender) if spender else ""
                                        amount_raw = params.get("value", "0")
                                        decimals = log.get("sender_contract_decimals", 0) or 0
                                        amount = float(amount_raw) / (10 ** decimals) if amount_raw else 0
                                        if amount > 1e15:
                                            amt_str = "∞"
                                        else:
                                            amt_str = f"{amount:,.2f}"
                                        st.write(f"📋 Approve {amt_str} {token_sym} → {spender_label}")
                                
                                if not has_approval:
                                    val_eth = float(tx["value_eth"])
                                    if val_eth > 0:
                                        is_out = (tx["from"] or "").lower() == resolved_addr.lower()
                                        direction = "🔴" if is_out else "🟢"
                                        sign = "-" if is_out else "+"
                                        cp = to_lbl if is_out else from_lbl
                                        st.write(f"{direction} {sign}{val_eth:.4f} {native_sym} (${tx['value_quote']:.2f}) { '→ ' + cp if cp else ''}")
                                    else:
                                        st.write(f"📎 {from_lbl} → {to_lbl}")
                            
                            st.caption(f"tx: {tx_link}")

                    with col_gas:
                        st.caption(f"gas: ${tx['gas_quote']:.4f}")

                    st.markdown("---")

                if len(tx_window) > display_count:
                    st.caption(f"Showing first {display_count} of {len(tx_window)} transactions. Use date filter to narrow down.")

        elif mode.startswith("📋"):
            # --- Transactions Mode (table view) ---
            if not tx_window.empty:
                daily_tx = tx_window.copy()
                daily_tx["date"] = daily_tx["block_signed_at"].dt.date
                daily_counts = daily_tx.groupby(["date", "chain"]).size().reset_index(name="count")
                fig_freq = px.bar(
                    daily_counts, x="date", y="count", color="chain",
                    title="Transaction Frequency",
                    color_discrete_map={k: CHAIN_COLORS.get(k, "#888") for k in daily_counts["chain"].unique()},
                )
                fig_freq.update_layout(
                    height=300, margin=dict(l=20, r=20, t=40, b=20),
                    paper_bgcolor="#ffffff", font_color="#1a1a1a",
                )
                st.plotly_chart(fig_freq, use_container_width=True)

            st.subheader("Transactions")
            tx_display = tx_window.copy()
            tx_display["from_label"] = tx_display["from"].apply(label_or_short)
            tx_display["to_label"] = tx_display["to"].apply(label_or_short)
            show_cols = ["block_signed_at", "from_label", "to_label", "chain", "value_eth", "value_quote", "gas_quote", "success", "tx_hash"]
            available_cols = [c for c in show_cols if c in tx_display.columns]
            st.dataframe(
                tx_display[available_cols],
                use_container_width=True,
                column_config={
                    "value_quote": st.column_config.NumberColumn(format="$%.2f"),
                    "gas_quote": st.column_config.NumberColumn(format="$%.4f"),
                    "block_signed_at": st.column_config.DatetimeColumn(format="YYYY-MM-DD HH:mm"),
                },
            )
            st.caption(f"{len(tx_window)} txs in selected timeframe.")

        # --- Export ---
        st.divider()
        st.download_button(
            "📥 Download transfers as CSV",
            tf_window.to_csv(index=False),
            file_name=f"transfers_{address}_{start_dt}_{end_dt}.csv",
            mime="text/csv",
        )
else:
    st.info("Enter a wallet address, select chains, and click **Fetch & Analyze** to start.")
