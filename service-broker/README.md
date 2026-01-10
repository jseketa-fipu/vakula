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
Copy `.env.example` to `.env` and adjust as needed:
- `BROKER_PORT` (default: 8001)

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
