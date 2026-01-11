# Gateway Service

API gateway and registrar for stations. Handles registration, heartbeats, and forwards adjust commands.

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
- `GATEWAY_PORT`
- `HEARTBEAT_TIMEOUT_SECONDS`

Example:
```bash
export GATEWAY_PORT=8000
export HEARTBEAT_TIMEOUT_SECONDS=60
```

## Run
```bash
PYTHONPATH=.. python server.py
```

## API Docs
FastAPI docs: `http://localhost:8000/docs`

## Key Endpoints
- `POST /api/register`
- `POST /api/stations/{station_id}/heartbeat`
- `GET /api/stations`
- `GET /api/stations/{station_id}`
- `POST /api/stations/{station_id}/adjust` (negative = degrade, positive = repair)
