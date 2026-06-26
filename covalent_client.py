"""Covalent (GoldRush) API client for wallet transaction history."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Iterator

import requests
from dotenv import load_dotenv

load_dotenv()

API_KEY = os.environ["COVALENT_API_KEY"]
BASE = "https://api.covalenthq.com/v1"
SESSION = requests.Session()
SESSION.headers.update({"Authorization": f"Bearer {API_KEY}"})


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
) -> Iterator[dict]:
    """Yield raw tx items for an address on a chain.

    chain: e.g. 'eth-mainnet', 'bsc-mainnet', 'base-mainnet'
    address: 0x... or ENS
    Pagination via Covalent's page-based scheme.
    """
    url = f"{BASE}/{chain}/address/{address}/transactions_v3/"
    params = {"page-size": page_size}
    if start_block is not None:
        params["starting-block"] = start_block
    if end_block is not None:
        params["ending-block"] = end_block

    pages = 0
    while url:
        data = _get(url, params=params)
        body = data.get("data", {})
        items = body.get("items", [])
        for it in items:
            yield it
        pages += 1
        if max_pages and pages >= max_pages:
            break
        # follow pagination link
        links = body.get("links", {})
        next_url = links.get("next")
        if not next_url:
            break
        url = next_url
        params = None  # next_url already has query string


def fetch_token_transfers(chain: str, address: str, page_size: int = 500) -> Iterator[dict]:
    """Fetch ERC-20/721 transfers for an address. Covalent exposes this via the
    same transactions_v3 endpoint — log_events with decoded Transfer events.
    We pull tx history and extract transfer logs. For heavy wallets, consider
    the bulk endpoint or filtering by block range."""
    for tx in fetch_transactions(chain, address, page_size=page_size):
        for log in tx.get("log_events", []) or []:
            decoded = log.get("decoded")
            if not decoded:
                continue
            if decoded.get("name") == "Transfer":
                yield _normalize_transfer(log, tx)


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
    for tx in fetch_transactions("eth-mainnet", "vitalik.eth", page_size=5, max_pages=1):
        print(tx["block_signed_at"], tx["tx_hash"][:18], "logs:", len(tx.get("log_events") or []))
