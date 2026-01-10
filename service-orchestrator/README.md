# Station Orchestrator Service

Creates new station containers via the Docker HTTP API.

## Requirements
- Python 3.11+
- Docker socket mounted at `/var/run/docker.sock`

## Setup
```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Configuration
Set required environment variables before running:
- `DOCKER_SOCKET`
- `DOCKER_API_VERSION`
- `GATEWAY_URL`
- `BROKER_URL`
- `STATION_IMAGE` (can be empty to reuse the gateway image)
- `ORCHESTRATOR_NETWORK`
- `ORCHESTRATOR_PORT`

Example:
```bash
export DOCKER_SOCKET=/var/run/docker.sock
export DOCKER_API_VERSION=v1.44
export GATEWAY_URL=http://localhost:8000
export BROKER_URL=http://localhost:8001
export STATION_IMAGE=
export ORCHESTRATOR_NETWORK=vakula
export ORCHESTRATOR_PORT=8003
```

## Run
```bash
python server.py
```

## API Docs
FastAPI docs: `http://localhost:8003/docs`

## Key Endpoints
- `POST /api/stations` (array only)

Request example:
```json
[
  { "name": "Aljmaš Planina", "lat": 45.528861, "lon": 18.972139 }
]
```
