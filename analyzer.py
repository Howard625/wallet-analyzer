"""Analysis layer: turn raw Covalent tx + log_events into DataFrames.

Key features:
- USD valuation via DexScreener (primary) + CoinGecko (fallback), both free
- DEX-aware transfer extraction: skips intermediate pool transfers in swap txs
- Unified ranking: counterparties + tokens mixed, sorted by USD volume
- Drill-down: filter to a specific counterparty or token
"""
from __future__ import annotations

import time
from datetime import datetime
from decimal import Decimal

import pandas as pd
import requests

from covalent_client import fetch_transactions, fetch_moralis_labels_batch, fetch_internal_transfers
from labels import get_label, ROUTERS, AGGREGATORS, BRIDGES

# Addresses that act as routing intermediaries (bridges, routers, aggregators).
# When a wallet's tx `to` is one of these, the tx is a routed/bridged action:
# the real counterparty is this intermediary, and funds may be forwarded on to
# a final recipient via internal transactions.
INTERMEDIARY_ADDRESSES = {
    a.lower() for a in list(ROUTERS) + list(AGGREGATORS) + list(BRIDGES)
}

# Bridges specifically. A bridge "Call Message In" often performs internal
# swaps + native internal transfers to the final recipient, so bridge txns get
# priority classification (even when Swap logs are present) and native
# internal-transfer resolution. Plain DEX routers/aggregators are NOT included
# here, so the wallet's own direct swaps still classify as 'dex_swap'.
BRIDGE_ADDRESSES = {a.lower() for a in BRIDGES}

# Chain mapping for DexScreener
DEXSCREENER_CHAIN_MAP = {
    "eth-mainnet": "ethereum",
    "bsc-mainnet": "bsc",
    "base-mainnet": "base",
    "arbitrum-mainnet": "arbitrum",
    "optimism-mainnet": "optimism",
    "polygon-mainnet": "polygon",
    "avalanche-mainnet": "avalanche",
}

# Chain mapping for CoinGecko
COINGECKO_CHAIN_MAP = {
    "eth-mainnet": "ethereum",
    "bsc-mainnet": "binance-smart-chain",
    "base-mainnet": "base",
    "arbitrum-mainnet": "arbitrum-one",
    "optimism-mainnet": "optimistic-ethereum",
    "polygon-mainnet": "polygon-pos",
    "avalanche-mainnet": "avalanche",
}

NATIVE_CG_ID = {
    "eth-mainnet": "ethereum",
    "bsc-mainnet": "binancecoin",
    "base-mainnet": "ethereum",
    "arbitrum-mainnet": "ethereum",
    "optimism-mainnet": "ethereum",
    "polygon-mainnet": "matic-network",
    "avalanche-mainnet": "avalanche-2",
}

NATIVE_SYMBOL = {
    "eth-mainnet": "ETH",
    "bsc-mainnet": "BNB",
    "base-mainnet": "ETH",
    "arbitrum-mainnet": "ETH",
    "optimism-mainnet": "ETH",
    "polygon-mainnet": "MATIC",
    "avalanche-mainnet": "AVAX",
}

STABLECOIN_SYMBOLS = {
    "USDT", "USDC", "BUSD", "DAI", "USD1", "USDD", "TUSD", "FRAX",
    "USDE", "USD0", "PYUSD", "GUSD", "USDP", "SUSDE", "USTC",
}

EXCLUDE_FROM_RANKING = STABLECOIN_SYMBOLS | {
    "ETH", "BNB", "WETH", "WBNB", "MATIC", "WMATIC", "AVAX", "WAVAX"
}


def _to_dec(s: str | None, decimals: int = 0) -> Decimal:
    if not s:
        return Decimal(0)
    try:
        return Decimal(s) / (Decimal(10) ** decimals)
    except Exception:
        return Decimal(0)


def _to_float(dec) -> float:
    try:
        return float(dec)
    except Exception:
        return 0.0


def fetch_token_prices(contracts: set, chains: list[str]) -> dict[str, float]:
    """Fetch USD prices for token contracts across multiple chains."""
    if not contracts:
        return {}

    prices = {}
    contract_list = [c for c in contracts if c and c.startswith("0x")]

    for chain in chains:
        ds_chain = DEXSCREENER_CHAIN_MAP.get(chain)
        if ds_chain and contract_list:
            for i in range(0, len(contract_list), 30):
                batch = contract_list[i:i + 30]
                addrs = ",".join(batch)
                url = f"https://api.dexscreener.com/tokens/v1/{ds_chain}/{addrs}"
                try:
                    r = requests.get(url, timeout=20)
                    if r.status_code == 200:
                        data = r.json()
                        if isinstance(data, list):
                            for pair in data:
                                base = pair.get("baseToken", {})
                                addr = (base.get("address") or "").lower()
                                price_str = pair.get("priceUsd")
                                if addr and price_str:
                                    try:
                                        p = float(price_str)
                                        if p > 0:
                                            prices[addr] = p
                                    except ValueError:
                                        pass
                except Exception:
                    pass
                if i + 30 < len(contract_list):
                    time.sleep(0.5)

        cg_platform = COINGECKO_CHAIN_MAP.get(chain)
        missing = [c for c in contract_list if c.lower() not in prices]
        if cg_platform and missing:
            for i in range(0, len(missing), 25):
                batch = missing[i:i + 25]
                addrs = ",".join(batch)
                url = f"https://api.coingecko.com/api/v3/simple/token_price/{cg_platform}"
                try:
                    r = requests.get(url, params={"contract_addresses": addrs, "vs_currencies": "usd"}, timeout=15)
                    if r.status_code == 200:
                        data = r.json()
                        for addr, info in data.items():
                            if isinstance(info, dict) and "usd" in info:
                                prices[addr.lower()] = float(info["usd"])
                except Exception:
                    pass
                if i + 25 < len(missing):
                    time.sleep(1.5)

        native_id = NATIVE_CG_ID.get(chain)
        if native_id:
            try:
                r = requests.get(
                    "https://api.coingecko.com/api/v3/simple/price",
                    params={"ids": native_id, "vs_currencies": "usd"}, timeout=10)
                if r.status_code == 200:
                    data = r.json()
                    if native_id in data and "usd" in data[native_id]:
                        prices[f"__native_{chain}__"] = float(data[native_id]["usd"])
            except Exception:
                pass

    return prices


def _classify_tx(tx: dict) -> str:
    """Classify a transaction: 'bridge', 'dex_swap', 'native_transfer', or 'other'.

    Bridge/router detection takes priority: bridges frequently perform internal
    swaps, so a Swap log alone does not mean the wallet did a direct DEX swap.
    If the tx `to` is a known bridge/router/aggregator intermediary, classify
    as 'bridge' so we resolve the real recipient (incl. native internal
    transfers) and tag the intermediary as the counterparty.
    """
    tx_to = (tx.get("to_address") or "").lower()
    if tx_to in BRIDGE_ADDRESSES:
        return "bridge"
    logs = tx.get("log_events") or []
    for log in logs:
        decoded = log.get("decoded")
        if decoded and decoded.get("name") == "Swap":
            return "dex_swap"
    return "other"


def _extract_swap_transfers(tx: dict, wallet_lower: str) -> list[dict]:
    """For a DEX swap tx, extract only the meaningful transfers.

    In a DEX swap, the user's wallet directly sends/receives tokens, but the
    counterparty (DEX aggregator like OKX DEX) is the tx `to` address.
    Intermediate pool addresses that the wallet sends to directly are just
    routing hops — replace them with the tx `to` address as the real counterparty.
    """
    logs = tx.get("log_events") or []
    tx_to = (tx.get("to_address") or "").lower()  # The DEX aggregator / router
    transfers = []

    for log in logs:
        decoded = log.get("decoded")
        if not decoded or decoded.get("name") != "Transfer":
            continue
        params = {}
        for p in (decoded.get("params") or []):
            if p.get("name") and p.get("value") is not None:
                params[p["name"]] = p["value"]

        from_addr = (params.get("from") or "").lower()
        to_addr = (params.get("to") or "").lower()

        # Only keep transfers where the wallet is directly involved
        if wallet_lower not in (from_addr, to_addr):
            continue

        decimals = log.get("sender_contract_decimals", 0) or 0
        amount = _to_float(_to_dec(params.get("value"), decimals))

        # Skip zero-value transfers (spam/scam tokens)
        if amount == 0:
            continue

        # Replace intermediate pool addresses with the DEX aggregator (tx.to)
        # If wallet sends to a pool (not the DEX aggregator itself),
        # the real counterparty is the DEX aggregator
        actual_from = params.get("from")
        actual_to = params.get("to")
        if from_addr == wallet_lower and to_addr != tx_to:
            # Wallet sent to an intermediate pool, but real counterparty is DEX
            actual_to = tx.get("to_address")  # use original case
        elif to_addr == wallet_lower and from_addr != tx_to:
            # Wallet received from an intermediate pool, real counterparty is DEX
            actual_from = tx.get("to_address")

        transfers.append({
            "from": actual_from,
            "to": actual_to,
            "token_symbol": log.get("sender_contract_ticker_symbol") or "UNKNOWN",
            "token_name": log.get("sender_name") or "Unknown",
            "token_contract": log.get("sender_address"),
            "token_decimals": decimals,
            "direction": "out" if from_addr == wallet_lower else "in",
            "amount": amount,
        })

    return transfers


def _extract_bridge_transfers(tx: dict, wallet_lower: str, chain: str | None = None,
                              native_price: float = 0.0, native_sym: str = "ETH") -> list[dict]:
    """For a bridge / routed call, resolve the real from -> to and tag the bridge.

    Pattern (e.g. Butter Bridge "Call Message In"):
      wallet initiates a tx to a bridge/router contract (tx.to = intermediary).
      The bridge forwards value on to a FINAL recipient via a chain of internal
      transfers. We want to show:
        from = wallet (tx initiator)
        to   = final recipient of the routed funds
        counterparty label (leftmost) = the bridge/router intermediary

    We follow the ERC20 Transfer chain and pick the last hop's `to` that is NOT
    an intermediary as the final recipient. Only emit when the wallet is the
    tx initiator (out) or the ultimate recipient (in).

    If the wallet is NOT present in any ERC20 hop (common when the bridge
    delivers NATIVE tokens, e.g. BNB, via internal transfers that are absent
    from log_events), we fetch the tx's native internal transfers and detect
    whether the wallet received/sent native value, tagging the bridge as the
    counterparty.
    """
    tx_from = (tx.get("from_address") or "").lower()
    tx_to = tx.get("to_address")            # the bridge/router (original case)
    tx_to_lower = (tx_to or "").lower()
    tx_hash = tx.get("tx_hash")
    logs = tx.get("log_events") or []

    # Collect all ERC20 Transfer hops in this tx
    hops = []
    wallet_in_erc20 = False
    for log in logs:
        decoded = log.get("decoded")
        if not decoded or decoded.get("name") != "Transfer":
            continue
        params = {}
        for p in (decoded.get("params") or []):
            if p.get("name") and p.get("value") is not None:
                params[p["name"]] = p["value"]
        decimals = log.get("sender_contract_decimals", 0) or 0
        amount = _to_float(_to_dec(params.get("value"), decimals))
        if amount == 0:
            continue
        h_from = (params.get("from") or "").lower()
        h_to = (params.get("to") or "").lower()
        if wallet_lower in (h_from, h_to):
            wallet_in_erc20 = True
        hops.append({
            "from": params.get("from"),
            "to": params.get("to"),
            "from_l": h_from,
            "to_l": h_to,
            "amount": amount,
            "token_symbol": log.get("sender_contract_ticker_symbol") or "UNKNOWN",
            "token_name": log.get("sender_name") or "Unknown",
            "token_contract": log.get("sender_address"),
            "token_decimals": decimals,
        })

    transfers = []

    # --- Native internal transfers (bridge delivers native BNB/ETH) ---
    # Only needed when the wallet isn't a direct ERC20 participant.
    if chain and tx_hash and not wallet_in_erc20:
        try:
            internals = fetch_internal_transfers(chain, tx_hash)
        except Exception:
            internals = []
        for it in internals:
            i_from = (it.get("from_address") or "").lower()
            i_to = (it.get("to_address") or "").lower()
            if wallet_lower not in (i_from, i_to):
                continue
            amt = _to_float(_to_dec(it.get("value"), 18))
            if amt == 0:
                continue
            direction = "in" if i_to == wallet_lower else "out"
            transfers.append({
                "from": (tx.get("from_address") if direction == "in" else it.get("from_address")),
                "to": (it.get("to_address") if direction == "in" else it.get("to_address")),
                "token_symbol": native_sym,
                "token_name": native_sym,
                "token_contract": None,
                "token_decimals": 18,
                "direction": direction,
                "amount": amt,
                "value_usd": amt * native_price if native_price else 0.0,
                "counterparty": tx_to,       # the bridge (leftmost label)
                "is_native": True,
            })
        if transfers:
            return transfers

    if not hops:
        return []

    # Final recipient = `to` of the last hop that is not itself an intermediary
    # and not the bridge. Fall back to the very last hop's `to`.
    final_recipient = None
    final_hop = None
    for h in hops:
        if h["to_l"] and h["to_l"] not in INTERMEDIARY_ADDRESSES and h["to_l"] != tx_to_lower:
            final_recipient = h["to"]
            final_hop = h
    if final_recipient is None:
        final_hop = hops[-1]
        final_recipient = final_hop["to"]

    # Case 1: wallet initiated the bridge call (out). Show wallet -> final recipient,
    # counterparty tagged as the bridge.
    if tx_from == wallet_lower:
        transfers.append({
            "from": tx.get("from_address"),
            "to": final_recipient,
            "token_symbol": final_hop["token_symbol"],
            "token_name": final_hop["token_name"],
            "token_contract": final_hop["token_contract"],
            "token_decimals": final_hop["token_decimals"],
            "direction": "out",
            "amount": final_hop["amount"],
            "counterparty": tx_to,          # the bridge/router (leftmost label)
        })
        return transfers

    # Case 2: wallet is the ultimate recipient of the routed funds (in).
    # Show initiator -> wallet, counterparty tagged as the bridge.
    for h in hops:
        if h["to_l"] == wallet_lower:
            transfers.append({
                "from": tx.get("from_address"),
                "to": h["to"],
                "token_symbol": h["token_symbol"],
                "token_name": h["token_name"],
                "token_contract": h["token_contract"],
                "token_decimals": h["token_decimals"],
                "direction": "in",
                "amount": h["amount"],
                "counterparty": tx_to,
            })

    return transfers


def _extract_simple_transfers(tx: dict, wallet_lower: str, chain: str, native_price: float, native_sym: str) -> list[dict]:
    """For non-swap txs, extract native + ERC20 transfers normally."""
    transfers = []

    # Native transfer
    vw = tx.get("value")
    if vw and vw != "0":
        from_addr = str(tx.get("from_address") or "").lower()
        to_addr = str(tx.get("to_address") or "").lower()
        if wallet_lower in (from_addr, to_addr):
            amount = _to_float(_to_dec(vw, 18))
            usd = amount * native_price if native_price else 0.0
            transfers.append({
                "from": tx.get("from_address"),
                "to": tx.get("to_address"),
                "token_symbol": native_sym,
                "token_name": native_sym,
                "token_contract": None,
                "token_decimals": 18,
                "direction": "out" if from_addr == wallet_lower else "in",
                "amount": amount,
                "value_usd": usd,
            })

    # ERC20 transfers
    for log in tx.get("log_events") or []:
        decoded = log.get("decoded")
        if not decoded or decoded.get("name") != "Transfer":
            continue
        params = {}
        for p in (decoded.get("params") or []):
            if p.get("name") and p.get("value") is not None:
                params[p["name"]] = p["value"]

        from_addr = (params.get("from") or "").lower()
        to_addr = (params.get("to") or "").lower()
        if wallet_lower not in (from_addr, to_addr):
            continue

        decimals = log.get("sender_contract_decimals", 0) or 0
        amount = _to_float(_to_dec(params.get("value"), decimals))
        token_sym = log.get("sender_contract_ticker_symbol") or "UNKNOWN"

        # Skip zero-value ERC20 transfers (spam/scam)
        if amount == 0:
            continue

        transfers.append({
            "from": params.get("from"),
            "to": params.get("to"),
            "token_symbol": token_sym,
            "token_name": log.get("sender_name") or "Unknown",
            "token_contract": log.get("sender_address"),
            "token_decimals": decimals,
            "direction": "out" if from_addr == wallet_lower else "in",
            "amount": amount,
            "value_usd": 0.0,  # filled later with prices
        })

    return transfers


def build_tx_dataframe(chain: str, address: str, max_pages: int | None = None) -> tuple[pd.DataFrame, str]:
    """Pull all transactions for a wallet and return a flat DataFrame."""
    items, resolved_address = fetch_transactions(chain, address, max_pages=max_pages)
    
    # Batch fetch labels from Moralis (one API call gets all counterparty labels)
    moralis_labels = fetch_moralis_labels_batch(address, chain)
    
    rows = []
    for tx in items:
        from_addr = tx.get("from_address") or ""
        to_addr = tx.get("to_address") or ""
        
        # Try: built-in labels → Moralis batch labels → empty
        from_lbl = get_label(from_addr, chain) or moralis_labels.get(from_addr.lower(), "")
        to_lbl = get_label(to_addr, chain) or moralis_labels.get(to_addr.lower(), "")
        
        rows.append({
            "block_signed_at": pd.to_datetime(tx.get("block_signed_at")),
            "tx_hash": tx.get("tx_hash"),
            "from": from_addr,
            "to": to_addr,
            "from_label": from_lbl,
            "to_label": to_lbl,
            "value_wei": tx.get("value"),
            "value_eth": _to_dec(tx.get("value"), 18),
            "value_quote": float(tx.get("value_quote") or 0),
            "gas_quote": float(tx.get("gas_quote") or 0),
            "success": tx.get("successful"),
            "log_events": tx.get("log_events") or [],
            "chain": chain,
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df.sort_values("block_signed_at", ascending=False, inplace=True)
    return df, resolved_address


def build_multi_chain_tx(chains: list[str], address: str, max_pages: int | None = None) -> tuple[pd.DataFrame, str]:
    """Fetch and merge transactions across multiple chains."""
    all_dfs = []
    resolved = address
    for chain in chains:
        try:
            df, res = build_tx_dataframe(chain, address, max_pages=max_pages)
            if not df.empty:
                all_dfs.append(df)
            if resolved == address:
                resolved = res
        except Exception as e:
            print(f"Warning: failed to fetch {chain}: {e}")
    if not all_dfs:
        return pd.DataFrame(), resolved
    merged = pd.concat(all_dfs, ignore_index=True)
    merged.sort_values("block_signed_at", ascending=False, inplace=True)
    return merged, resolved


def extract_transfers(df: pd.DataFrame, wallet: str, prices: dict[str, float]) -> pd.DataFrame:
    """Extract transfers with DEX-awareness.

    For DEX swap transactions, only keep transfers where the wallet is
    directly the sender or receiver — skip intermediate pool-to-pool hops.
    """
    if df.empty:
        return pd.DataFrame()
    wallet_lower = wallet.lower()
    out = []

    for _, tx in df.iterrows():
        chain = tx["chain"]
        native_key = f"__native_{chain}__"
        native_price = prices.get(native_key, prices.get("__native__", 0.0))
        native_sym = NATIVE_SYMBOL.get(chain, "ETH")

        # Reconstruct raw tx dict for classification
        tx_dict = {
            "from_address": tx["from"],
            "to_address": tx["to"],
            "value": tx["value_wei"],
            "log_events": tx["log_events"],
            "tx_hash": tx["tx_hash"],
        }

        tx_type = _classify_tx(tx_dict)

        if tx_type == "dex_swap":
            # DEX swap: only keep wallet's direct transfers
            swap_transfers = _extract_swap_transfers(tx_dict, wallet_lower)
            for t in swap_transfers:
                contract = (t["token_contract"] or "").lower()
                token_price = prices.get(contract, 0.0)
                token_sym = t["token_symbol"]
                if not token_price and token_sym.upper() in STABLECOIN_SYMBOLS:
                    token_price = 1.0
                usd = t["amount"] if token_price == 1.0 and token_sym.upper() in STABLECOIN_SYMBOLS else (t.get("amount", 0) * token_price if token_price else 0.0)

                # Recalculate amount properly
                decimals = t["token_decimals"]
                # amount already computed in _extract_swap_transfers? No, we need to compute it
                # Actually _extract_swap_transfers doesn't compute amount, let me fix

                out.append({
                    "block_signed_at": tx["block_signed_at"],
                    "tx_hash": tx["tx_hash"],
                    "from": t["from"],
                    "to": t["to"],
                    "token_symbol": token_sym,
                    "token_name": t["token_name"],
                    "token_contract": t["token_contract"],
                    "token_decimals": decimals,
                    "token_type": "erc20",
                    "chain": chain,
                    "direction": t["direction"],
                    "amount": t.get("amount", 0),
                    "value_usd": usd,
                    "counterparty": None,
                })
        elif tx_type == "bridge":
            # Bridge / routed call: resolve real from -> final recipient,
            # tag the bridge/router as the counterparty (leftmost label).
            # Also pulls native internal transfers when the wallet only
            # received/sent native BNB/ETH via the bridge (not in log_events).
            bridge_transfers = _extract_bridge_transfers(
                tx_dict, wallet_lower, chain=chain,
                native_price=native_price, native_sym=native_sym,
            )
            for t in bridge_transfers:
                if t.get("is_native"):
                    # USD already computed from native price in the extractor.
                    usd = t.get("value_usd", 0.0)
                    token_type = "native"
                else:
                    contract = (t["token_contract"] or "").lower()
                    token_price = prices.get(contract, 0.0)
                    token_sym = t["token_symbol"]
                    if not token_price and token_sym.upper() in STABLECOIN_SYMBOLS:
                        token_price = 1.0
                    usd = t["amount"] if token_price == 1.0 and token_sym.upper() in STABLECOIN_SYMBOLS else (t.get("amount", 0) * token_price if token_price else 0.0)
                    token_type = "erc20"

                out.append({
                    "block_signed_at": tx["block_signed_at"],
                    "tx_hash": tx["tx_hash"],
                    "from": t["from"],
                    "to": t["to"],
                    "token_symbol": t["token_symbol"],
                    "token_name": t["token_name"],
                    "token_contract": t["token_contract"],
                    "token_decimals": t["token_decimals"],
                    "token_type": token_type,
                    "chain": chain,
                    "direction": t["direction"],
                    "amount": t.get("amount", 0),
                    "value_usd": usd,
                    "counterparty": t.get("counterparty"),
                })
        else:
            # Normal tx: extract all transfers
            simple = _extract_simple_transfers(tx_dict, wallet_lower, chain, native_price, native_sym)
            for t in simple:
                contract = (t["token_contract"] or "").lower()
                token_price = prices.get(contract, 0.0)
                token_sym = t["token_symbol"]
                if not token_price and token_sym.upper() in STABLECOIN_SYMBOLS:
                    token_price = 1.0
                usd = t["amount"] * token_price if token_price else 0.0

                out.append({
                    "block_signed_at": tx["block_signed_at"],
                    "tx_hash": tx["tx_hash"],
                    "from": t["from"],
                    "to": t["to"],
                    "token_symbol": token_sym,
                    "token_name": t["token_name"],
                    "token_contract": t["token_contract"],
                    "token_decimals": t["token_decimals"],
                    "token_type": "native" if t["token_contract"] is None else "erc20",
                    "chain": chain,
                    "direction": t["direction"],
                    "amount": t["amount"],
                    "value_usd": usd,
                    "counterparty": None,
                })

    return pd.DataFrame(out)


def unified_ranking(transfers: pd.DataFrame, wallet: str) -> pd.DataFrame:
    """DeBank-style unified ranking: counterparties + tokens mixed together."""
    if transfers.empty:
        return pd.DataFrame()

    wallet_lower = wallet.lower()

    # --- Counterparty ranking ---
    cp = transfers.copy()
    # Prefer an explicit counterparty override (e.g. bridge/router intermediary)
    # when present; otherwise fall back to the non-wallet side of the transfer.
    def _cp(r):
        override = r["counterparty"]
        # Treat NaN / None / empty as "no override"
        if override is not None and not (isinstance(override, float) and pd.isna(override)) and str(override).strip():
            return override
        return r["to"] if (r["from"] or "").lower() == wallet_lower else r["from"]
    if "counterparty" not in cp.columns:
        cp["counterparty"] = None
    cp["counterparty"] = cp.apply(_cp, axis=1)
    cp = cp[cp["counterparty"].notna() & (cp["counterparty"] != "")]

    cp_stats = cp.groupby("counterparty").agg(
        tx_count=("tx_hash", "nunique"),
        total_usd=("value_usd", "sum"),
        in_count=("direction", lambda s: (s == "in").sum()),
        out_count=("direction", lambda s: (s == "out").sum()),
        first_seen=("block_signed_at", "min"),
        last_seen=("block_signed_at", "max"),
    ).reset_index()
    cp_stats["entity_type"] = "address"
    cp_stats = cp_stats.rename(columns={"counterparty": "entity"})
    cp_stats["token_amount"] = ""
    cp_stats["token_symbol"] = ""
    cp_stats["label"] = cp_stats["entity"].apply(lambda a: get_label(a) or "")
    cp_stats["display_name"] = cp_stats.apply(
        lambda r: r["label"] if r["label"] else (r["entity"][:6] + "…" + r["entity"][-4:] if len(str(r["entity"])) > 14 else r["entity"]),
        axis=1,
    )

    # --- Token ranking (exclude stablecoins and native tokens) ---
    tk = transfers.copy()
    tk = tk[~tk["token_symbol"].str.upper().isin(EXCLUDE_FROM_RANKING)]
    tk_stats = tk.groupby(["token_symbol", "token_name", "token_contract"]).agg(
        tx_count=("tx_hash", "nunique"),
        total_usd=("value_usd", "sum"),
        in_count=("direction", lambda s: (s == "in").sum()),
        out_count=("direction", lambda s: (s == "out").sum()),
        first_seen=("block_signed_at", "min"),
        last_seen=("block_signed_at", "max"),
        token_amount=("amount", "sum"),
    ).reset_index()
    tk_stats["entity_type"] = "token"
    tk_stats["entity"] = tk_stats["token_symbol"]
    tk_stats = tk_stats.drop(columns=["token_name", "token_contract"])
    tk_stats["label"] = ""
    tk_stats["display_name"] = tk_stats["entity"]

    combined = pd.concat([cp_stats, tk_stats], ignore_index=True)
    combined = combined.sort_values(["total_usd", "tx_count"], ascending=[False, False])

    cols = ["display_name", "entity", "entity_type", "tx_count", "in_count", "out_count", "total_usd", "token_amount", "token_symbol", "label", "first_seen", "last_seen"]
    combined = combined[[c for c in cols if c in combined.columns]]

    return combined.reset_index(drop=True)


def filter_by_entity(transfers: pd.DataFrame, wallet: str, entity: str, entity_type: str) -> pd.DataFrame:
    """Drill-down: filter transfers to only those involving a specific entity."""
    if transfers.empty:
        return transfers

    wallet_lower = wallet.lower()

    if entity_type == "address":
        ent = entity.lower()
        def _match(r):
            cp = r["counterparty"] if "counterparty" in r else None
            if cp is None or (isinstance(cp, float) and pd.isna(cp)):
                cp = ""
            addrs = [
                (r["from"] or "").lower(),
                (r["to"] or "").lower(),
                str(cp).lower(),
            ]
            return ent in addrs and ent != wallet_lower
        mask = transfers.apply(_match, axis=1)
    else:
        mask = transfers["token_symbol"].str.lower() == entity.lower()

    return transfers[mask].sort_values("block_signed_at", ascending=False)


def filter_by_timeframe(df: pd.DataFrame, start: datetime, end: datetime, ts_col="block_signed_at") -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    if start_ts.tzinfo is None:
        start_ts = start_ts.tz_localize("UTC")
    if end_ts.tzinfo is None:
        end_ts = end_ts.tz_localize("UTC")
    mask = (df[ts_col] >= start_ts) & (df[ts_col] <= end_ts)
    return df.loc[mask].sort_values(ts_col, ascending=False)


def build_swap_summaries(df: pd.DataFrame, wallet: str, transfers: pd.DataFrame | None = None) -> pd.DataFrame:
    """Build human-readable swap summaries from transactions.

    For each DEX swap tx, show:
    - What was spent (token_out, amount_out, usd_out)
    - What was received (token_in, amount_in, usd_in)
    - Which DEX (counterparty)
    - Timestamp
    Multiple swaps in the same tx_hash are merged into one row with totals.
    """
    if df.empty:
        return pd.DataFrame()
    wallet_lower = wallet.lower()
    rows = []
    
    # Build a lookup: tx_hash -> {token_symbol: {direction: usd_sum}}
    tx_token_usd = {}
    if transfers is not None and not transfers.empty:
        for _, t in transfers.iterrows():
            h = t["tx_hash"]
            sym = (t.get("token_symbol") or "").upper()
            d = t.get("direction", "")
            usd = float(t.get("value_usd", 0) or 0)
            if h not in tx_token_usd:
                tx_token_usd[h] = {}
            key = f"{sym}_{d}"
            tx_token_usd[h][key] = tx_token_usd[h].get(key, 0) + usd

    # Group by tx_hash to merge multiple swaps in same tx
    for tx_hash, tx_group in df.groupby("tx_hash"):
        first = tx_group.iloc[0]
        tx_dict = {
            "from_address": first["from"],
            "to_address": first["to"],
            "value": first["value_wei"],
            "log_events": first["log_events"],
        }
        if _classify_tx(tx_dict) != "dex_swap":
            continue

        all_outs = {}
        all_ins = {}
        for _, tx in tx_group.iterrows():
            td = {
                "from_address": tx["from"],
                "to_address": tx["to"],
                "value": tx["value_wei"],
                "log_events": tx["log_events"],
            }
            swap_transfers = _extract_swap_transfers(td, wallet_lower)
            for t in swap_transfers:
                sym = t["token_symbol"]
                if t["direction"] == "out":
                    all_outs[sym] = all_outs.get(sym, 0) + t["amount"]
                else:
                    all_ins[sym] = all_ins.get(sym, 0) + t["amount"]

        if not all_outs and not all_ins:
            continue

        dex_label = get_label(first["to"]) or ""
        dex_name = dex_label or (first["to"][:10] + "..." if first["to"] else "")

        # Build spent/received strings with USD
        spent_parts = []
        for sym, amt in all_outs.items():
            if amt < 0.0001:  # Skip dust amounts
                continue
            usd = tx_token_usd.get(tx_hash, {}).get(f"{sym.upper()}_out", 0)
            if sym.upper() in STABLECOIN_SYMBOLS and usd == 0:
                usd = amt  # stablecoin = $1
            usd_str = f" (${usd:,.2f})" if usd > 0 else ""
            spent_parts.append(f"{amt:,.4f} {sym}{usd_str}")
        
        received_parts = []
        for sym, amt in all_ins.items():
            if amt < 0.0001:  # Skip dust amounts
                continue
            usd = tx_token_usd.get(tx_hash, {}).get(f"{sym.upper()}_in", 0)
            if sym.upper() in STABLECOIN_SYMBOLS and usd == 0:
                usd = amt
            usd_str = f" (${usd:,.2f})" if usd > 0 else ""
            received_parts.append(f"{amt:,.4f} {sym}{usd_str}")

        spent_str = " + ".join(spent_parts) if spent_parts else ""
        received_str = " + ".join(received_parts) if received_parts else ""

        rows.append({
            "block_signed_at": first["block_signed_at"],
            "tx_hash": tx_hash,
            "chain": first["chain"],
            "dex": dex_name,
            "spent": spent_str,
            "received": received_str,
        })

    return pd.DataFrame(rows).sort_values("block_signed_at", ascending=False) if rows else pd.DataFrame()


def get_first_fund(df: pd.DataFrame, transfers: pd.DataFrame | None = None, wallet: str = "") -> dict | None:
    """Get the earliest transaction (first fund) for a wallet.

    Looks for the first native token transfer with value (BNB/ETH).
    This is more reliable than ERC20 for tracing fund origins —
    exchange withdrawals are native token transfers.
    """
    if df.empty:
        return None
    
    # Find earliest tx with non-zero native value
    valued = df[df["value_eth"] != 0]
    if valued.empty:
        # No native value transfers — fall back to earliest tx
        valued = df
    
    earliest = valued.loc[valued["block_signed_at"].idxmin()]
    from_addr = earliest["from"] or ""
    from_label = earliest.get("from_label", "") or get_label(from_addr) or ""
    return {
        "timestamp": earliest["block_signed_at"],
        "from": from_addr,
        "to": earliest["to"] or "",
        "from_label": from_label,
        "to_label": earliest.get("to_label", "") or "",
        "value_eth": float(earliest["value_eth"]),
        "value_quote": earliest["value_quote"],
        "tx_hash": earliest["tx_hash"],
        "chain": earliest["chain"],
        "success": earliest["success"],
        "token_symbol": "",
        "amount": 0.0,
    }
