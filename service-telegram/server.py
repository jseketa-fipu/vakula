import aiohttp
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
from vakula_common.http import create_session
from vakula_common.logging import setup_logger

log = setup_logger("TELEGRAM")

CLIENT_SESSION: aiohttp.ClientSession | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global CLIENT_SESSION
    CLIENT_SESSION = create_session(10)
    try:
        yield
    finally:
        if CLIENT_SESSION:
            await CLIENT_SESSION.close()


app = FastAPI(title="Vakula Telegram Notifier", lifespan=lifespan)

TELEGRAM_BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
# https://stackoverflow.com/questions/32423837/telegram-bot-how-to-get-a-group-chat-id


class SendMessageRequest(BaseModel):
    message: str
    chat_id: str
    parse_mode: str | None = None


class SendMessageResponse(BaseModel):
    ok: bool
    telegram_response: Dict[Any, Any]


def _require_telegram_token() -> str:
    # Fail fast when the bot token is missing.
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not set")
    return TELEGRAM_BOT_TOKEN


@app.post("/api/send", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    token: str = Depends(_require_telegram_token),
) -> SendMessageResponse:
    # Send a message to the Telegram Bot API.
    # This service is a thin wrapper around Telegram's HTTP endpoint.
    payload = {"chat_id": request.chat_id, "text": request.message}
    if request.parse_mode:
        payload["parse_mode"] = request.parse_mode

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with CLIENT_SESSION.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except aiohttp.ClientError as e:
        log.warning(f"Telegram send failed: {e!r}")
        raise HTTPException(status_code=502, detail="Telegram API request failed")

    return SendMessageResponse(ok=True, telegram_response=data)


def main() -> None:
    # Run the API server.
    port = int(os.environ["TELEGRAM_SERVICE_PORT"])
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
