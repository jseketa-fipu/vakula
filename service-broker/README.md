# Broker Service

Aggregates station state and broadcasts to the frontend over WebSockets.

## Requirements
- Python 3.11+

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration
Set required environment variables before running:
- `BROKER_PORT`
- `BROKER_STALE_SECONDS`
- `TELEGRAM_URL`

Example:
```bash
export BROKER_PORT=8001
export BROKER_STALE_SECONDS=30
export TELEGRAM_URL=http://localhost:8002
```

## Run
```bash
python server.py
```

## API Docs
FastAPI docs: `http://localhost:8001/docs`

## Key Endpoints
- `POST /api/station-update`
- `GET /api/state`
- `WS /ws`
