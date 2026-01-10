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
Copy `.env.example` to `.env` and adjust as needed:
- `GATEWAY_URL` (default: http://localhost:8000)
- `TICK_SECONDS` (default: 5.0)

## Run
```bash
python server.py
```
