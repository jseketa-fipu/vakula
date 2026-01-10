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
Set required environment variables before running:
- `GATEWAY_URL`
- `BROKER_URL`
- `STATION_NAME`
- `STATION_ID`
- `STATION_LAT`
- `STATION_LON`
- `PUBLIC_BASE_URL`
- `PORT`

Example:
```bash
export GATEWAY_URL=http://localhost:8000
export BROKER_URL=http://localhost:8001
export STATION_NAME=ExampleStation
export STATION_ID=1001
export STATION_LAT=45.815
export STATION_LON=15.982
export PUBLIC_BASE_URL=http://localhost:9000
export PORT=9000
```

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
