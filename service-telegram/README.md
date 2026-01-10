# Telegram Service

Accepts a message and sends it to a Telegram chat via a bot token.

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
- `TELEGRAM_BOT_TOKEN` (required)
- `TELEGRAM_CHAT_ID` (optional default chat id)
- `TELEGRAM_SERVICE_PORT` (default: 8002)

## Run
```bash
python server.py
```

## API Docs
FastAPI docs: `http://localhost:8002/docs`

## Key Endpoints
- `POST /api/send`
