# Wallet Transaction Analyzer

A DeBank-style wallet analysis tool built on Covalent (GoldRush) API + Streamlit.

## Features
- Fetch all transactions for any wallet on 8+ chains
- Three analysis views:
  - **Counterparties** — top addresses by interaction count, with in/out split
  - **Tokens** — net flow per token (inflow - outflow)
  - **Raw transactions** — full tx history with filters
- Timeframe filter (date range)
- CSV export

## Setup

```bash
cd wallet-analyzer
pip install -r requirements.txt

# put your Covalent API key in .env
echo "COVALENT_API_KEY=your_key_here" > .env
chmod 600 .env

# run
streamlit run app.py --server.port 8501 --server.headless true
```

Open http://localhost:8501

## Files
- `covalent_client.py` — API client, fetches tx history + extracts token transfers
- `analyzer.py` — pandas-based analysis (counterparty summary, token flows, timeframe filter)
- `app.py` — Streamlit UI
- `.env` — API key (gitignore this)

## Cost
- Covalent free tier: 100k calls/month — enough for personal use
- Streamlit: free
- Total: $0

## Notes
- For heavy wallets (10k+ txs), increase max_pages or use block range filtering
- Covalent's `transactions_v3` endpoint returns decoded log events, so token
  transfers don't need a separate API call
