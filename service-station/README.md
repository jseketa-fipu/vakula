# Station Service

Simulates a single physical weather station. Tracks module health and pushes state to the broker.

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
- `GATEWAY_URL` (default: http://localhost:8000)
- `BROKER_URL` (default: http://localhost:8001)
- `STATION_NAME` (default: ExampleStation)
- `STATION_ID` (optional: stable ID for broker/gateway)
- `STATION_LAT` (optional: station latitude)
- `STATION_LON` (optional: station longitude)
- `PUBLIC_BASE_URL` (default: http://localhost:9000)
- `PORT` (default: 9000)

## Run
```bash
python server.py
```

## API Docs
FastAPI docs: `http://localhost:9000/docs`

## Key Endpoints
- `GET /state`
- `POST /adjust` (negative = degrade, positive = repair)
- `POST /bootstrap`
