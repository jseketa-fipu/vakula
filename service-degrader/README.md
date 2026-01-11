# Degrader Service

Background service that periodically adjusts random station modules via the gateway.

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
- `TICK_SECONDS`

Example:
```bash
export GATEWAY_URL=http://localhost:8000
export TICK_SECONDS=5.0
```

## Run
```bash
PYTHONPATH=.. python server.py
```
