#!/bin/zsh
set -e

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

if [ ! -f ".env" ]; then
  echo "ERROR: .env file not found."
  echo "Create $ROOT/.env with your existing Upstox + Supabase credentials."
  exit 1
fi

set -a
source .env
set +a

if [ -z "$UPSTOX_ACCESS_TOKEN" ]; then
  echo "ERROR: UPSTOX_ACCESS_TOKEN is missing in .env"
  exit 1
fi
if [ -z "$SUPABASE_URL" ] || [ -z "$SUPABASE_SERVICE_ROLE_KEY" ]; then
  echo "ERROR: SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY is missing in .env"
  exit 1
fi

if [ ! -d ".venv" ]; then
  echo "Creating Python virtual environment..."
  python3 -m venv .venv
fi

source .venv/bin/activate

echo "Installing/updating Python dependencies..."
python -m pip install --upgrade pip
python -m pip install -r requirements.txt

echo ""
echo "=============================================="
echo " PRIME TECHNICAL LIVE SCANNER"
echo "=============================================="
echo "Starting Upstox -> Prime Engine -> Supabase"
echo "Keep this Terminal window open."
echo "Press Ctrl+C to stop."
echo "=============================================="
echo ""

exec python -m worker.scanner_worker
