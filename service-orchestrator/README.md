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
Copy `.env.example` to `.env` and adjust as needed:
- `DOCKER_SOCKET` (default: /var/run/docker.sock)
- `DOCKER_API_VERSION` (default: v1.43)
- `GATEWAY_URL` (default: http://gateway:8000)
- `BROKER_URL` (default: http://broker:8001)
- `STATION_IMAGE` (optional: Docker image to use for new stations)
- `ORCHESTRATOR_PORT` (default: 8003)

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
