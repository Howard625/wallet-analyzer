"""Analysis layer: turn raw Covalent tx + log_events into DataFrames.

Three core views (mirroring DeBank's old analysis feature):
1. Counterparty analysis — top addresses this wallet interacts with
2. Token analysis — net flow per token
3. Time-windowed transactions — all txs in a date range
"""
from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pandas as pd

from covalent_client import fetch_transactions


def _to_dec(s: str | None, decimals: int = 0) -> Decimal:
    if not s:
        return Decimal(0)
    try:
        return Decimal(s) / (Decimal(10) ** decimals)
    except Exception:
        return Decimal(0)


def build_tx_dataframe(chain: str, address: str, max_pages: int | None = None) -> pd.DataFrame:
    """Pull all transactions for a wallet and return a flat DataFrame."""
    rows = []
    for tx in fetch_transactions(chain, address, max_pages=max_pages):
        rows.append({
            "block_signed_at": pd.to_datetime(tx.get("block_signed_at")),
            "tx_hash": tx.get("tx_hash"),
            "from": tx.get("from_address"),
            "to": tx.get("to_address"),
            "value_wei": tx.get("value"),
            "value_eth": _to_dec(tx.get("value"), 18),
            "gas_quote": tx.get("gas_quote"),
            "success": tx.get("successful"),
            "log_events": tx.get("log_events") or [],
            "chain": chain,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values("block_signed_at", ascending=False, inplace=True)
    return df


def extract_token_transfers(df: pd.DataFrame) -> pd.DataFrame:
    """From a tx DataFrame, explode log_events into token transfers."""
    if df.empty:
        return pd.DataFrame()
    out = []
    for _, tx in df.iterrows():
        for log in tx["log_events"]:
            decoded = log.get("decoded")
            if not decoded or decoded.get("name") != "Transfer":
                continue
            params = {p["name"]: p["value"] for p in decoded.get("params", [])}
            decimals = log.get("sender_contract_decimals", 0) or 0
            out.append({
                "block_signed_at": tx["block_signed_at"],
                "tx_hash": tx["tx_hash"],
                "from": params.get("from"),
                "to": params.get("to"),
                "value_raw": params.get("value"),
                "value": _to_dec(params.get("value"), decimals),
                "token_contract": log.get("sender_address"),
                "token_name": log.get("sender_name"),
                "token_symbol": log.get("sender_contract_ticker_symbol"),
                "token_type": "erc721" if "erc721" in (log.get("supports_erc") or []) else "erc20",
                "chain": tx["chain"],
            })
    return pd.DataFrame(out)


def counterparty_summary(transfers: pd.DataFrame, wallet: str) -> pd.DataFrame:
    """Top counterparties by interaction volume (count + total value).

    Groups by the OTHER party in each transfer (whichever of from/to isn't wallet).
    """
    if transfers.empty:
        return pd.DataFrame()
    wallet = wallet.lower()
    transfers = transfers.copy()
    transfers["counterparty"] = transfers.apply(
        lambda r: r["to"] if (r["from"] or "").lower() == wallet else r["from"],
        axis=1,
    )
    transfers["direction"] = transfers.apply(
        lambda r: "out" if (r["from"] or "").lower() == wallet else "in",
        axis=1,
    )
    summary = transfers.groupby("counterparty").agg(
        tx_count=("tx_hash", "nunique"),
        total_value=("value", "sum"),
        in_count=("direction", lambda s: (s == "in").sum()),
        out_count=("direction", lambda s: (s == "out").sum()),
        first_seen=("block_signed_at", "min"),
        last_seen=("block_signed_at", "max"),
    ).sort_values("tx_count", ascending=False)
    return summary


def token_summary(transfers: pd.DataFrame, wallet: str) -> pd.DataFrame:
    """Net flow per token."""
    if transfers.empty:
        return pd.DataFrame()
    wallet = wallet.lower()
    transfers = transfers.copy()
    transfers["direction"] = transfers.apply(
        lambda r: "out" if (r["from"] or "").lower() == wallet else "in",
        axis=1,
    )
    transfers["signed_value"] = transfers.apply(
        lambda r: r["value"] if r["direction"] == "in" else -r["value"],
        axis=1,
    )
    summary = transfers.groupby(["token_symbol", "token_name", "token_contract"]).agg(
        tx_count=("tx_hash", "nunique"),
        total_in=("value", lambda s: s[transfers.loc[s.index, "direction"] == "in"].sum()),
        total_out=("value", lambda s: s[transfers.loc[s.index, "direction"] == "out"].sum()),
        net_flow=("signed_value", "sum"),
        first_seen=("block_signed_at", "min"),
        last_seen=("block_signed_at", "max"),
    ).sort_values("tx_count", ascending=False)
    return summary


def filter_by_timeframe(df: pd.DataFrame, start: datetime, end: datetime, ts_col="block_signed_at") -> pd.DataFrame:
    mask = (df[ts_col] >= pd.Timestamp(start, tz="UTC")) & (df[ts_col] <= pd.Timestamp(end, tz="UTC"))
    return df.loc[mask].sort_values(ts_col, ascending=False)
