# Talosly — DeFi Security Alert System

> AI monitors your protocol 24/7. Risk scores every transaction 0-100.
> Fires Telegram alerts before hacks complete. Free beta.

## What Is Talosly?

Talosly is an automated DeFi security monitoring system. Add your Ethereum
contract address. Talosly watches transactions hitting your protocol, scores
each one for risk using OpenAI GPT-4o-mini, and sends instant Telegram alerts for
anything suspicious.

Most protocols cannot afford enterprise security monitoring before they have
serious traction. Talosly gives early teams a focused security alert layer they
can run before they raise.

## How It Works

1. Add your protocol's contract address to Talosly.
2. The monitoring worker checks Ethereum activity when RPC polling is enabled.
3. Layer 1 filters obvious safe/noisy transactions.
4. Layer 2 extracts exploit-oriented transaction features.
5. Layer 3 routes high-risk transactions using ML models or heuristic fallback.
6. Layer 4 / OpenAI scoring produces a 0-100 risk score for escalated transactions.
7. Score above 70 creates an alert and sends Telegram notification.
8. Full transaction and alert history is available on the dashboard.

## Tech Stack

- **Backend:** Python 3.11 + FastAPI
- **Worker:** Python asyncio polling loop
- **Database:** PostgreSQL
- **Frontend:** React 18 + Vite
- **Risk Scoring:** Layer 3 ML/heuristics + OpenAI GPT-4o-mini escalation
- **Blockchain:** Ethereum JSON-RPC, Alchemy compatible
- **Alerts:** Telegram Bot API
- **Deploy:** Docker Compose

## Beta Access

Talosly is currently in free beta. Apply from the landing page.

## Running Locally

### Prerequisites

- Docker + Docker Compose
- Alchemy API key or Ethereum RPC URL
- OpenAI API key
- Telegram bot token and chat ID

### Setup

```bash
cp .env.example .env
# Fill in your API keys in .env
cd frontend && npm install && npm run build && cd ..
docker compose up -d
```

Initialize the database:

```bash
docker compose exec backend python scripts/init_db.py
```

Create your first API key:

```bash
docker compose exec backend python scripts/create_api_key.py --name "Dev key"
```

Open:

- Frontend: http://localhost
- API health: http://localhost/api/health
- Dashboard: http://localhost/dashboard
- Admin: http://localhost/admin

## API

Health and waitlist routes are public. Product API routes require:

```text
Authorization: Bearer tals_xxxxx
```

Examples:

```bash
curl http://localhost/api/health
```

```bash
curl -X POST http://localhost/api/protocols \
  -H "Authorization: Bearer tals_xxxxx" \
  -H "Content-Type: application/json" \
  -d '{"name": "Uniswap V3", "address": "0xE592427A0AEce92De3Edee1F18E0157C05861564"}'
```

```bash
curl "http://localhost/api/transactions?protocol_id=1" \
  -H "Authorization: Bearer tals_xxxxx"
```

```bash
curl http://localhost/api/alerts \
  -H "Authorization: Bearer tals_xxxxx"
```

## Admin

Admin endpoints require:

```text
X-Admin-Secret: your_admin_secret
```

Admin can:

- list waitlist applications
- approve/reject beta access
- generate one-time API keys
- revoke API keys
- view metrics and usage

## Architecture

```mermaid
flowchart LR
  User[User Browser] --> Vercel[Vercel Static Frontend]
  Vercel -->|VITE_API_URL /api/*| Backend[Railway FastAPI Backend]
  Backend --> Auth[API Key / Admin Auth]
  Backend --> DB[(PostgreSQL)]
  Backend --> OpenAI[OpenAI API]

  Worker[Railway Worker] --> DB
  Worker -->|optional HTTP polling| Alchemy[Alchemy / Ethereum RPC]
  Worker -->|optional mempool WS| AlchemyWS[Alchemy WebSocket]
  Worker --> OpenAI
  Worker --> Telegram[Telegram Bot]

  Backend --> FrontendData[Dashboard Data]
  FrontendData --> Vercel
```

### Deployment Split

```mermaid
flowchart TD
  subgraph Vercel
    FE[React + Vite dist]
  end

  subgraph Railway
    API[FastAPI API]
    Worker[Background Worker]
    PG[(PostgreSQL)]
  end

  FE -->|VITE_API_URL| API
  API --> PG
  Worker --> PG
  Worker -->|ENABLE_RPC_POLLING=true| RPC[Ethereum RPC]
  Worker -->|ENABLE_RPC_POLLING=false| Idle[Idle / no Alchemy usage]
```

### Transaction Workflow

```mermaid
sequenceDiagram
  participant RPC as Ethereum RPC
  participant W as Worker
  participant L1 as Layer 1 Filter
  participant L2 as Layer 2 Features
  participant L3 as Layer 3 ML/Heuristic
  participant L4 as Layer 4 OpenAI
  participant DB as PostgreSQL
  participant TG as Telegram

  W->>RPC: Fetch latest block / txs
  RPC-->>W: Transactions
  W->>L1: Pre-filter transaction
  alt safe/noisy transaction
    L1-->>W: skip
    W->>DB: store skip metadata
  else suspicious transaction
    L1-->>L2: extract features
    L2-->>L3: feature vector
    alt Layer 3 below threshold
      L3-->>W: store and skip
      W->>DB: save transaction + Layer 3 result
    else Layer 3 escalates
      L3-->>L4: escalate to scorer
      L4-->>W: risk score 0-100
      W->>DB: save score and alert if needed
      opt score >= risk threshold
        W->>TG: send alert
      end
    end
  end
```

### Layer 3 Scoring Modes

```mermaid
flowchart TD
  Tx[Layer 2 Feature Vector] --> Enabled{ENABLE_LAYER3_ML?}
  Enabled -- false --> Heuristic[Heuristic Fallback]
  Enabled -- true --> Models{Model files valid?}
  Models -- yes --> ML[Isolation Forest + GBM + Bayesian + Platt]
  Models -- no --> Heuristic
  ML --> Result[ensemble_score + mode=ml]
  Heuristic --> Result2[ensemble_score + mode=heuristic]
  Result --> Gate{score >= LAYER3_ESCALATION_THRESHOLD}
  Result2 --> Gate
  Gate -- yes --> L4[Layer 4 / OpenAI]
  Gate -- no --> Skip[Store and skip]
```

### Runtime Controls

For Railway worker deployments:

```env
ENABLE_RPC_POLLING=false
POLL_INTERVAL_SECONDS=3600
ETHEREUM_BLOCKS_PER_POLL=1
ETHEREUM_INITIAL_LOOKBACK_BLOCKS=0
ETHEREUM_RPC_MIN_INTERVAL_SECONDS=5.0
ETHEREUM_RPC_MAX_RETRIES=1
ETHEREUM_RPC_RATE_LIMIT_BACKOFF_SECONDS=3600

ENABLE_LAYER3_ML=true
LAYER3_MODEL_DIR=models
LAYER3_ESCALATION_THRESHOLD=0.55
```

For Vercel frontend deployments:

```env
VITE_API_URL=https://talosly-startup-production.up.railway.app
```

## Development Checks

```bash
python3 -m pytest tests/
cd frontend && npm run build
```

## Status

Talosly v0.2.0 is a free beta launch build. It is designed for early user
testing, accelerator demos, and low-cost monitoring experiments.

Built with Codex. Monitoring DeFi so you do not have to.
