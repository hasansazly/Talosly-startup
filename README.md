# Talosly — DeFi Security Alert System

## Setup

1. Copy `.env.example` to `.env` and fill in your API keys
2. Install Python deps: `pip install -r requirements.txt`
3. Install frontend deps: `cd frontend && npm install`

## Running

Terminal 1 — API server:
```bash
uvicorn backend.main:app --reload --port 8000
```

Terminal 2 — Worker:
```bash
python -m backend.worker
```

Terminal 3 — Frontend:
```bash
cd frontend && npm run dev
```

Open http://localhost:5173

## Quick Start

1. Open the dashboard
2. Click "Add Protocol" and enter any Ethereum contract address to monitor
3. The worker will start scanning new blocks every 15 seconds
4. Transactions above risk score 70 trigger a Telegram alert

## Test address

High-activity contract for testing:
- Uniswap V3: `0xE592427A0AEce92De3Edee1F18E0157C05861564`

## Tests

```bash
pytest tests/
```
