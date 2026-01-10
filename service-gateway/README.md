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
Copy `.env.example` to `.env` and adjust as needed:
- `GATEWAY_PORT` (default: 8000)
- `HEARTBEAT_TIMEOUT_SECONDS` (default: 60)

## Run
```bash
python server.py
```

## API Docs
FastAPI docs: `http://localhost:8000/docs`

## Key Endpoints
- `POST /api/register`
- `POST /api/stations/{station_id}/heartbeat`
- `GET /api/stations`
- `POST /api/stations/{station_id}/adjust` (negative = degrade, positive = repair)
