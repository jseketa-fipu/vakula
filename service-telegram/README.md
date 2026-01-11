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
Set required environment variables before running:
- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `TELEGRAM_SERVICE_PORT`

Example:
```bash
export TELEGRAM_BOT_TOKEN=your_bot_token
export TELEGRAM_CHAT_ID=your_chat_id
export TELEGRAM_SERVICE_PORT=8002
```

## Run
```bash
PYTHONPATH=.. python server.py
```

## API Docs
FastAPI docs: `http://localhost:8002/docs`

## Key Endpoints
- `POST /api/send`
