#!/bin/bash
# Wallet Analyzer startup script
# Usage: ./start.sh

cd "$(dirname "$0")"

# Activate venv if not already active
if [ -z "$VIRTUAL_ENV" ]; then
  source .venv/bin/activate
fi

# Check venv exists
if [ ! -d ".venv" ]; then
  echo "❌ .venv not found. Run this first:"
  echo "   python3.12 -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt"
  exit 1
fi

# Check .env exists
if [ ! -f ".env" ]; then
  echo "❌ .env not found. Create it with:"
  echo "   echo 'COVALENT_API_KEY=***' > .env"
  exit 1
fi

echo "🚀 Starting Wallet Transaction Analyzer..."
echo "   Browser will open at http://localhost:8501"
echo "   Press Ctrl+C to stop"
echo ""

streamlit run app.py
