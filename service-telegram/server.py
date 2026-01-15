import aiohttp
import os
import uvicorn
from contextlib import asynccontextmanager
from fastapi import Depends, FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
from vakula_common import HttpClient, setup_logger

log = setup_logger("TELEGRAM")
HTTP_CLIENT = HttpClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    HTTP_CLIENT.create_session(10)
    try:
        yield
    finally:
        await HTTP_CLIENT.session.close()


app = FastAPI(title="Vakula Telegram Notifier", lifespan=lifespan)

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")
# https://stackoverflow.com/questions/32423837/telegram-bot-how-to-get-a-group-chat-id


class SendMessageRequest(BaseModel):
    message: str
    chat_id: str | None = None
    parse_mode: str | None = None


class SendMessageResponse(BaseModel):
    ok: bool
    telegram_response: Dict[Any, Any]


def _require_telegram_token() -> str:
    # Fail fast when the bot token is missing.
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not set")
    return TELEGRAM_BOT_TOKEN


def _resolve_chat_id(request: SendMessageRequest) -> str:
    # Prefer request chat_id, fallback to configured default.
    chat_id = request.chat_id or TELEGRAM_CHAT_ID
    if not chat_id:
        raise HTTPException(
            status_code=500,
            detail="TELEGRAM_CHAT_ID is not set and no chat_id was provided",
        )
    return chat_id


@app.post("/api/send", response_model=SendMessageResponse)
async def send_message(
    request: SendMessageRequest,
    token: str = Depends(_require_telegram_token),
) -> SendMessageResponse:
    # Send a message to the Telegram Bot API.
    # This service is a thin wrapper around Telegram's HTTP endpoint.
    chat_id = _resolve_chat_id(request)
    payload = {"chat_id": chat_id, "text": request.message}
    if request.parse_mode:
        payload["parse_mode"] = request.parse_mode

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        async with HTTP_CLIENT.session.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except aiohttp.ClientError as e:
        log.warning(f"Telegram send failed: {e!r}")
        raise HTTPException(status_code=502, detail="Telegram API request failed")

    return SendMessageResponse(ok=True, telegram_response=data)


def main() -> None:
    # Run the API server.
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=int(os.environ["TELEGRAM_SERVICE_PORT"]),
        reload=False,
    )


if __name__ == "__main__":
    main()
