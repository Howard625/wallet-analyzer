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
from labels import label_or_short, get_label
from analyzer import INTERMEDIARY_ADDRESSES, BRIDGE_ADDRESSES

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


def _address_link(addr: str) -> str:
    """Return full address with label if available."""
    if not addr:
        return ""
    label = get_label(addr)
    if label:
        return f"{label}\n({addr})"
    return addr


def _render_pagination(total_pages: int, current_page: int, key_prefix: str,
                       total_txs: int, start_idx: int, end_idx: int) -> None:
    """Render clickable numbered pagination with a 5-page sliding window,
    First/Prev/Next/Last arrows, and a manual page-jump input.

    Window logic: show up to 5 page numbers centered on the current page,
    always keeping the first and last page reachable (with ellipsis when there
    is a gap). Examples for 14 pages:
      p1  -> [1] 2 3 4 5 … 14
      p4  -> 1 2 3 [4] 5 6 … 14
      p10 -> 1 … 8 9 [10] 11 12 … 14
      p14 -> 1 … 10 11 12 13 [14]
    """
    if total_pages <= 1:
        return

    st.caption(f"Showing {start_idx + 1}-{min(end_idx, total_txs)} of {total_txs} · Page {current_page + 1} / {total_pages}")

    WINDOW = 5

    def _page_list() -> list:
        # Few pages: show them all.
        if total_pages <= WINDOW + 2:
            return list(range(total_pages))
        start = max(0, current_page - WINDOW // 2)
        end = min(total_pages - 1, start + WINDOW - 1)
        start = max(0, end - WINDOW + 1)
        out = []
        if start > 0:
            out.append(0)
            if start > 1:
                out.append(None)  # ellipsis
        out.extend(range(start, end + 1))
        if end < total_pages - 1:
            if end < total_pages - 2:
                out.append(None)  # ellipsis
            out.append(total_pages - 1)
        return out

    page_items = _page_list()

    # Layout: [First][Prev] [numbers...] [Next][Last]
    n_slots = len(page_items)
    col_specs = [1, 1] + [1] * n_slots + [1, 1]
    cols = st.columns(col_specs)

    with cols[0]:
        if st.button("⏮", key=f"{key_prefix}_first", help="First page", disabled=current_page == 0):
            st.session_state["tx_page"] = 0
            st.rerun()
    with cols[1]:
        if st.button("◀", key=f"{key_prefix}_prev", help="Previous", disabled=current_page == 0):
            st.session_state["tx_page"] = max(0, current_page - 1)
            st.rerun()

    for i, p in enumerate(page_items):
        with cols[2 + i]:
            if p is None:
                st.markdown("<div style='text-align:center;padding-top:8px'>…</div>", unsafe_allow_html=True)
            elif p == current_page:
                st.button(f"【{p + 1}】", key=f"{key_prefix}_cur_{p}", disabled=True)
            else:
                if st.button(f"{p + 1}", key=f"{key_prefix}_p_{p}"):
                    st.session_state["tx_page"] = p
                    st.rerun()

    with cols[2 + n_slots]:
        if st.button("▶", key=f"{key_prefix}_next", help="Next", disabled=current_page >= total_pages - 1):
            st.session_state["tx_page"] = min(total_pages - 1, current_page + 1)
            st.rerun()
    with cols[3 + n_slots]:
        if st.button("⏭", key=f"{key_prefix}_last", help="Last page", disabled=current_page >= total_pages - 1):
            st.session_state["tx_page"] = total_pages - 1
            st.rerun()

    # Manual jump: number input + Go button (only worth showing for many pages).
    if total_pages > WINDOW + 2:
        jc1, jc2, jc3 = st.columns([2, 1, 6])
        with jc1:
            target = st.number_input(
                "Jump to page", min_value=1, max_value=total_pages,
                value=current_page + 1, step=1, key=f"{key_prefix}_jump_input",
                label_visibility="collapsed",
            )
        with jc2:
            if st.button("Go", key=f"{key_prefix}_jump_go"):
                st.session_state["tx_page"] = int(target) - 1
                st.rerun()


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
        st.session_state["tx_page"] = 0
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
                    st.caption(f"tx: [{first_fund['tx_hash']}]({ff_explorer}{first_fund['tx_hash']}) | chain: {ff_chain}")
                else:
                    st.caption(f"tx: {first_fund['tx_hash']} | chain: {ff_chain}")
                
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
                                    st.markdown(f"🔴 -{swap['spent']}")
                                if swap["received"]:
                                    st.markdown(f"🟢 +{swap['received']}")
                            with c3:
                                explorer_url = CHAIN_EXPLORER.get(chain_tag, "")
                                if explorer_url:
                                    st.markdown(f"[tx: {swap['tx_hash']}]({explorer_url}{swap['tx_hash']})")
                                else:
                                    st.caption(f"tx: {swap['tx_hash']}")

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

                # --- Custom token search ---
                st.divider()
                # All tokens present in transfers (not just ranked ones)
                all_tokens = sorted(tf_window["token_symbol"].dropna().unique())
                search_col1, search_col2 = st.columns([3, 1])
                with search_col1:
                    custom_token = st.text_input(
                        "🔍 Search a specific token (symbol)",
                        placeholder="e.g. USDT, O, ZEST...",
                        key="custom_token_search",
                    )
                with search_col2:
                    st.markdown("<div style='padding-top:28px'></div>", unsafe_allow_html=True)
                    if st.button("Filter", key="custom_filter_btn", use_container_width=True):
                        if custom_token.strip():
                            matched = [t for t in all_tokens if str(t).upper() == custom_token.strip().upper()]
                            if matched:
                                st.session_state["drill_entity"] = matched[0]
                                st.session_state["drill_type"] = "token"
                                st.rerun()
                            else:
                                st.warning(f"Token '{custom_token}' not found in this wallet's transfers.")
                if all_tokens:
                    st.caption(f"Available tokens ({len(all_tokens)}): {', '.join(str(t) for t in all_tokens[:40])}{'...' if len(all_tokens) > 40 else ''}")

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

                # Pagination
                PAGE_SIZE = 20
                total_txs = len(tx_window)
                total_pages = max(1, (total_txs + PAGE_SIZE - 1) // PAGE_SIZE)
                
                if "tx_page" not in st.session_state:
                    st.session_state["tx_page"] = 0
                # Reset page if out of range (e.g. new address fetched)
                if st.session_state["tx_page"] >= total_pages:
                    st.session_state["tx_page"] = 0
                
                current_page = st.session_state["tx_page"]
                start_idx = current_page * PAGE_SIZE
                end_idx = start_idx + PAGE_SIZE
                page_txs = tx_window.iloc[start_idx:end_idx]
                
                for _, tx in page_txs.iterrows():
                    time_str = tx["block_signed_at"].strftime("%Y-%m-%d %H:%M:%S")
                    from_lbl = label_or_short(tx["from"])
                    to_lbl = label_or_short(tx["to"])
                    native_sym = CHAIN_NATIVE.get(tx["chain"], "ETH")
                    chain_color = CHAIN_COLORS.get(tx["chain"], "#888")
                    explorer_url = CHAIN_EXPLORER.get(tx["chain"], "")
                    tx_hash = tx["tx_hash"]
                    tx_link = f"[{tx_hash}]({explorer_url}{tx_hash})"

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
                                st.markdown(f"🔴 -{swap['spent']}")
                            if swap["received"]:
                                st.markdown(f"🟢 +{swap['received']}")
                            # Clickable token filters for each token in the swap.
                            swap_syms = []
                            for _sym, _amt in (_parse_swap_tokens(swap["spent"]) + _parse_swap_tokens(swap["received"])):
                                if _sym and _sym not in swap_syms:
                                    swap_syms.append(_sym)
                            if swap_syms:
                                tcols = st.columns(min(len(swap_syms), 4))
                                for _i, _sym in enumerate(swap_syms):
                                    with tcols[_i % len(tcols)]:
                                        if st.button(f"📊 {_sym}", key=f"tok_swap_{tx_hash}_{_sym}", help=f"Filter all {_sym} transfers"):
                                            st.session_state["drill_entity"] = _sym
                                            st.session_state["drill_type"] = "token"
                                            st.rerun()
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
                                        cp_override = t["counterparty"] if "counterparty" in t and pd.notna(t["counterparty"]) and str(t["counterparty"]).strip() else None
                                        cp_addr = (cp_override or t["to"]) or ""
                                        cp_display = _address_link(cp_addr)
                                        tsym = t["token_symbol"]
                                        tc1, tc2 = st.columns([5, 2])
                                        with tc1:
                                            st.markdown(f"🔴 -{t['amount']:,.4f} {tsym}{usd_str}")
                                            st.caption(f"→ {cp_display}")
                                        with tc2:
                                            if tsym and st.button(f"📊 {tsym}", key=f"tok_out_{t['tx_hash']}_{t.name}", help=f"Filter all {tsym} transfers"):
                                                st.session_state["drill_entity"] = tsym
                                                st.session_state["drill_type"] = "token"
                                                st.rerun()
                                        if st.button(f"🔍 Analyze {cp_addr[:10]}...", key=f"btn_out_{t['tx_hash']}_{t.name}"):
                                            st.session_state["pending_address"] = cp_addr
                                            st.rerun()
                                if not ins.empty:
                                    for _, t in ins.iterrows():
                                        usd_str = f" (${t['value_usd']:,.2f})" if t["value_usd"] > 0 else ""
                                        cp_override = t["counterparty"] if "counterparty" in t and pd.notna(t["counterparty"]) and str(t["counterparty"]).strip() else None
                                        cp_addr = (cp_override or t["from"]) or ""
                                        cp_display = _address_link(cp_addr)
                                        tsym = t["token_symbol"]
                                        tc1, tc2 = st.columns([5, 2])
                                        with tc1:
                                            st.markdown(f"🟢 +{t['amount']:,.4f} {tsym}{usd_str}")
                                            st.caption(f"← {cp_display}")
                                        with tc2:
                                            if tsym and st.button(f"📊 {tsym}", key=f"tok_in_{t['tx_hash']}_{t.name}", help=f"Filter all {tsym} transfers"):
                                                st.session_state["drill_entity"] = tsym
                                                st.session_state["drill_type"] = "token"
                                                st.rerun()
                                        if st.button(f"🔍 Analyze {cp_addr[:10]}...", key=f"btn_in_{t['tx_hash']}_{t.name}"):
                                            st.session_state["pending_address"] = cp_addr
                                            st.rerun()
                            else:
                                # Bridge / router interaction: if the tx `to` is a known
                                # bridge/router/aggregator, label it clearly at the left.
                                tx_to_addr = (tx["to"] or "")
                                is_intermediary = tx_to_addr.lower() in BRIDGE_ADDRESSES
                                if is_intermediary:
                                    bridge_label = get_label(tx_to_addr) or label_or_short(tx_to_addr)
                                    st.markdown(
                                        f"**🌉 {bridge_label}** <span style='color:#999;font-size:12px'>via {label_or_short(tx_to_addr)}</span>",
                                        unsafe_allow_html=True,
                                    )

                                # Collect Approve events and collapse them (spam reduction).
                                approvals = []
                                for log in tx["log_events"]:
                                    decoded = log.get("decoded")
                                    if not decoded or decoded.get("name") != "Approval":
                                        continue
                                    params = {}
                                    for p in (decoded.get("params") or []):
                                        if p.get("name") and p.get("value") is not None:
                                            params[p["name"]] = p["value"]
                                    token_sym = log.get("sender_contract_ticker_symbol") or ""
                                    spender = params.get("spender", "")
                                    amount_raw = params.get("value", "0")
                                    decimals = log.get("sender_contract_decimals", 0) or 0
                                    amount = float(amount_raw) / (10 ** decimals) if amount_raw else 0
                                    if amount == 0:
                                        continue
                                    approvals.append((token_sym, spender, amount))

                                has_approval = len(approvals) > 0
                                if has_approval:
                                    # Group by (token, spender); show max amount per group.
                                    grouped = {}
                                    for token_sym, spender, amount in approvals:
                                        key = (token_sym, spender)
                                        grouped[key] = max(grouped.get(key, 0), amount)

                                    total_approves = len(approvals)
                                    uniq = len(grouped)
                                    if total_approves > 1:
                                        # Collapsed summary line + expandable detail
                                        header = f"📋 {total_approves}× Approve"
                                        # Summarize dominant token
                                        toks = {t for (t, _), _ in grouped.items()}
                                        tok_str = list(toks)[0] if len(toks) == 1 else "tokens"
                                        st.markdown(f"{header} {tok_str} <span style='color:#999;font-size:12px'>({uniq} unique spender{'s' if uniq != 1 else ''}, click to expand)</span>", unsafe_allow_html=True)
                                        with st.expander("Show approvals"):
                                            for (token_sym, spender), amount in sorted(grouped.items(), key=lambda kv: -kv[1]):
                                                spender_label = label_or_short(spender) if spender else ""
                                                amt_str = "∞" if amount > 1e15 else f"{amount:,.2f}"
                                                st.write(f"📋 Approve {amt_str} {token_sym} → {spender_label}")
                                    else:
                                        (token_sym, spender), amount = next(iter(grouped.items()))
                                        spender_label = label_or_short(spender) if spender else ""
                                        amt_str = "∞" if amount > 1e15 else f"{amount:,.2f}"
                                        st.write(f"📋 Approve {amt_str} {token_sym} → {spender_label}")

                                if not has_approval:
                                    val_eth = float(tx["value_eth"])
                                    if val_eth > 0:
                                        is_out = (tx["from"] or "").lower() == resolved_addr.lower()
                                        direction = "🔴" if is_out else "🟢"
                                        sign = "-" if is_out else "+"
                                        cp_addr = (tx["to"] if is_out else tx["from"]) or ""
                                        cp_display = _address_link(cp_addr)
                                        st.markdown(f"{direction} {sign}{val_eth:.4f} {native_sym} (${tx['value_quote']:.2f})")
                                        st.caption(f"{'→' if is_out else '←'} {cp_display}")
                                        if st.button(f"🔍 Analyze {cp_addr[:10]}...", key=f"btn_native_{tx_hash}"):
                                            st.session_state["pending_address"] = cp_addr
                                            st.rerun()
                                    else:
                                        from_display = _address_link(tx["from"])
                                        to_display = _address_link(tx["to"])
                                        st.caption(f"📎 {from_display} → {to_display}")
                            
                            st.caption(f"tx: {tx_link}")

                    with col_gas:
                        st.caption(f"gas: ${tx['gas_quote']:.4f}")

                    st.markdown("---")

                # Pagination controls (list view)
                if total_pages > 1:
                    _render_pagination(total_pages, current_page, "lpg", total_txs, start_idx, end_idx)

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

            # Pagination controls
            if total_pages > 1:
                _render_pagination(total_pages, current_page, "pg", total_txs, start_idx, end_idx)

        # --- Export ---
        st.divider()
        if st.session_state.get("drill_entity"):
            # Filtered view: only download the filtered token's transfers
            entity_name = st.session_state["drill_entity"]
            st.download_button(
                f"📥 Download {entity_name} transfers as CSV",
                drilled.to_csv(index=False),
                file_name=f"transfers_{address}_{entity_name}_{start_dt}_{end_dt}.csv",
                mime="text/csv",
            )
        else:
            st.download_button(
                "📥 Download transfers as CSV",
                tf_window.to_csv(index=False),
                file_name=f"transfers_{address}_{start_dt}_{end_dt}.csv",
                mime="text/csv",
            )
else:
    st.info("Enter a wallet address, select chains, and click **Fetch & Analyze** to start.")
