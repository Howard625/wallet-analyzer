"""Covalent (GoldRush) API client for wallet transaction history."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass

import requests
from dotenv import load_dotenv

load_dotenv()

# Support both .env (local) and Streamlit secrets (cloud)
try:
    import streamlit as st
    _secrets = st.secrets
    API_KEY = _secrets.get("COVALENT_API_KEY", os.environ.get("COVALENT_API_KEY", ""))
    ETHERSCAN_API_KEY = _secrets.get("ETHERSCAN_API_KEY", os.environ.get("ETHERSCAN_API_KEY", ""))
    MORALIS_API_KEY = _secrets.get("MORALIS_API_KEY", os.environ.get("MORALIS_API_KEY", ""))
except Exception:
    API_KEY = os.environ.get("COVALENT_API_KEY", "")
    ETHERSCAN_API_KEY = os.environ.get("ETHERSCAN_API_KEY", "")
    MORALIS_API_KEY = os.environ.get("MORALIS_API_KEY", "")

BASE = "https://api.covalenthq.com/v1"
SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"Bearer {API_KEY}"})

# Etherscan V2 API key (for address label lookup)
ETHERSCAN_CHAIN_IDS = {
    "eth-mainnet": 1,
    "bsc-mainnet": 56,
    "base-mainnet": 8453,
    "arbitrum-mainnet": 42161,
    "optimism-mainnet": 10,
    "polygon-mainnet": 137,
    "avalanche-mainnet": 43114,
}

# Moralis API key (for address label lookup on BSC)
MORALIS_CHAIN_MAP = {
    "eth-mainnet": "eth",
    "bsc-mainnet": "bsc",
    "base-mainnet": "base",
    "arbitrum-mainnet": "arbitrum",
    "optimism-mainnet": "optimism",
    "polygon-mainnet": "polygon",
    "avalanche-mainnet": "avalanche",
}

# Runtime cache for dynamically fetched labels
_dynamic_labels: dict[str, str | None] = {}


def fetch_address_label(address: str, chain: str) -> str | None:
    """Fetch address label from Etherscan V2 API or Moralis API.
    Returns label string or None. Cached in memory after first lookup.
    """
    if not address:
        return None
    addr_lower = address.lower()
    cache_key = f"{chain}:{addr_lower}"
    if cache_key in _dynamic_labels:
        return _dynamic_labels[cache_key]

    # Try Etherscan first (ETH only on free tier)
    label = _fetch_etherscan_label(address, chain)
    if label:
        _dynamic_labels[cache_key] = label
        return label

    # Try Moralis (works for BSC and others)
    label = _fetch_moralis_label(address, chain)
    _dynamic_labels[cache_key] = label
    return label


def _fetch_etherscan_label(address: str, chain: str) -> str | None:
    if not ETHERSCAN_API_KEY:
        return None
    chain_id = ETHERSCAN_CHAIN_IDS.get(chain)
    if not chain_id:
        return None
    try:
        url = f"https://api.etherscan.io/v2/api?chainid={chain_id}&module=account&action=addresstag&address={address}"
        r = SESSION.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            if data.get("status") == "1":
                result = data.get("result", "")
                if result and result != "-":
                    return result
    except Exception:
        pass
    return None


def _fetch_moralis_label(address: str, chain: str) -> str | None:
    """Fetch address label from Moralis wallet history API.
    Searches recent transactions for this address and extracts labels.
    """
    if not MORALIS_API_KEY:
        return None
    moralis_chain = MORALIS_CHAIN_MAP.get(chain)
    if not moralis_chain:
        return None
    try:
        # Use Moralis wallet history to find labels for this address
        url = f"https://deep-index.moralis.io/api/v2.2/wallets/{address}/history?chain={moralis_chain}&limit=5"
        r = SESSION.get(url, headers={"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}, timeout=15)
        if r.status_code != 200:
            return None
        data = r.json()
        results = data.get("result", [])
        for tx in results:
            # Check tx-level labels
            if tx.get("from_address", "").lower() == address.lower() and tx.get("from_address_label"):
                return tx["from_address_label"]
            if tx.get("to_address", "").lower() == address.lower() and tx.get("to_address_label"):
                return tx["to_address_label"]
            # Check erc20 transfer labels
            for t in tx.get("erc20_transfers", []):
                if t.get("from_address", "").lower() == address.lower() and t.get("from_address_label"):
                    return t["from_address_label"]
                if t.get("to_address", "").lower() == address.lower() and t.get("to_address_label"):
                    return t["to_address_label"]
            # Check native transfer labels
            for t in tx.get("native_transfers", []):
                if t.get("from_address", "").lower() == address.lower() and t.get("from_address_label"):
                    return t["from_address_label"]
                if t.get("to_address", "").lower() == address.lower() and t.get("to_address_label"):
                    return t["to_address_label"]
    except Exception:
        pass
    return None


def fetch_moralis_labels_batch(address: str, chain: str, max_pages: int = 3) -> dict[str, str]:
    """Batch fetch labels from Moralis wallet history for a wallet.
    Returns {address_lower: label} dict.
    More efficient than per-address lookups — one API call gets labels for
    all counterparties in the wallet's recent transactions.
    """
    if not MORALIS_API_KEY:
        return {}
    moralis_chain = MORALIS_CHAIN_MAP.get(chain)
    if not moralis_chain:
        return {}

    labels = {}
    cursor = None
    for _ in range(max_pages):
        url = f"https://deep-index.moralis.io/api/v2.2/wallets/{address}/history?chain={moralis_chain}&limit=100"
        if cursor:
            url += f"&cursor={cursor}"
        try:
            r = SESSION.get(url, headers={"X-API-Key": MORALIS_API_KEY, "Accept": "application/json"}, timeout=20)
            if r.status_code != 200:
                break
            data = r.json()
            results = data.get("result", [])
            for tx in results:
                # TX level
                for prefix in ("from", "to"):
                    addr = tx.get(f"{prefix}_address")
                    label = tx.get(f"{prefix}_address_label")
                    if addr and label:
                        labels[addr.lower()] = label
                # Transfer level
                for field in ("erc20_transfers", "native_transfers"):
                    for t in tx.get(field, []):
                        for prefix in ("from", "to"):
                            addr = t.get(f"{prefix}_address")
                            label = t.get(f"{prefix}_address_label")
                            if addr and label:
                                labels[addr.lower()] = label
            cursor = data.get("cursor")
            if not cursor:
                break
        except Exception:
            break
    return labels


@dataclass
class TxPage:
    chain: str
    address: str
    page: int
    items: list[dict]
    has_next: bool
    next_url: str | None


def _get(url: str, params: dict | None = None, retries: int = 3) -> dict:
    """GET with retry/backoff for 429/5xx."""
    for i in range(retries):
        r = SESSION.get(url, params=params, timeout=30)
        if r.status_code == 200:
            return r.json()
        if r.status_code in (429, 500, 502, 503, 504):
            time.sleep(2 ** i)
            continue
        r.raise_for_status()
    raise RuntimeError(f"GET {url} failed after {retries} retries")


def fetch_transactions(
    chain: str,
    address: str,
    page_size: int = 500,
    max_pages: int | None = None,
    start_block: int | None = None,
    end_block: int | None = None,
) -> tuple[list[dict], str]:
    """Yield (tx_items, resolved_address) for an address on a chain.

    chain: e.g. 'eth-mainnet', 'bsc-mainnet', 'base-mainnet'
    address: 0x... or ENS
    Returns (list_of_tx_items, resolved_address_string).
    """
    url = f"{BASE}/{chain}/address/{address}/transactions_v3/"
    params = {"page-size": page_size}
    if start_block is not None:
        params["starting-block"] = start_block
    if end_block is not None:
        params["ending-block"] = end_block

    pages = 0
    resolved_address = address
    all_items = []
    while url:
        data = _get(url, params=params)
        body = data.get("data", {})
        if pages == 0:
            resolved_address = body.get("address", address)
        items = body.get("items", [])
        all_items.extend(items)
        pages += 1
        if max_pages and pages >= max_pages:
            break
        # Follow pagination link to OLDER transactions.
        links = body.get("links", {})
        prev_url = links.get("prev")
        if not prev_url:
            break
        url = prev_url
        params = None
    return all_items, resolved_address


# Cache internal transfers per (chain, tx_hash) to avoid duplicate API calls
_internal_tx_cache: dict[str, list[dict]] = {}


def fetch_internal_transfers(chain: str, tx_hash: str) -> list[dict]:
    """Fetch native-token internal transfers for a single transaction.

    Uses Covalent's transaction_v2 endpoint with `with-internal=true`, which
    returns native (e.g. BNB/ETH) internal transfers that are NOT present in
    log_events. Each item: {from_address, to_address, value, gas_limit}.
    Cached per (chain, tx_hash). Returns [] on any error.
    """
    if not tx_hash:
        return []
    key = f"{chain}:{tx_hash.lower()}"
    if key in _internal_tx_cache:
        return _internal_tx_cache[key]
    result: list[dict] = []
    try:
        url = f"{BASE}/{chain}/transaction_v2/{tx_hash}/"
        data = _get(url, params={"with-internal": "true"})
        items = (data.get("data") or {}).get("items") or []
        if items:
            result = items[0].get("internal_transfers") or []
    except Exception:
        result = []
    _internal_tx_cache[key] = result
    return result


def fetch_token_transfers(chain: str, address: str, page_size: int = 500) -> list[dict]:
    """Fetch ERC-20/721 transfers for an address."""
    items, _ = fetch_transactions(chain, address, page_size=page_size)
    result = []
    for tx in items:
        for log in tx.get("log_events", []) or []:
            decoded = log.get("decoded")
            if not decoded:
                continue
            if decoded.get("name") == "Transfer":
                result.append(_normalize_transfer(log, tx))
    return result


def _normalize_transfer(log: dict, tx: dict) -> dict:
    params = {p["name"]: p["value"] for p in log.get("decoded", {}).get("params", [])}
    return {
        "block_signed_at": tx.get("block_signed_at"),
        "tx_hash": tx.get("tx_hash"),
        "from": params.get("from"),
        "to": params.get("to"),
        "value": params.get("value"),
        "token_contract": log.get("sender_address"),
        "token_name": log.get("sender_name"),
        "token_symbol": log.get("sender_contract_ticker_symbol"),
        "token_decimals": log.get("sender_contract_decimals"),
        "token_type": "erc20" if "erc20" in (log.get("supports_erc") or []) else "erc721",
        "chain": tx.get("chain_name"),
    }


if __name__ == "__main__":
    # quick smoke test
    items, resolved = fetch_transactions("eth-mainnet", "vitalik.eth", page_size=5, max_pages=1)
    print(f"resolved: {resolved}")
    for tx in items:
        print(tx["block_signed_at"], tx["tx_hash"][:18], "logs:", len(tx.get("log_events") or []))
