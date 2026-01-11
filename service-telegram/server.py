import aiohttp
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import Any, Dict
from vakula_common.http import create_session
from vakula_common.env import get_env_int, get_env_str
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

TELEGRAM_BOT_TOKEN = get_env_str("TELEGRAM_BOT_TOKEN")
# https://stackoverflow.com/questions/32423837/telegram-bot-how-to-get-a-group-chat-id
DEFAULT_CHAT_ID = get_env_str("TELEGRAM_CHAT_ID")


class SendMessageRequest(BaseModel):
    message: str
    chat_id: str | None = None
    parse_mode: str | None = None


class SendMessageResponse(BaseModel):
    ok: bool
    telegram_response: Dict[Any, Any]


def _get_chat_id(req: SendMessageRequest) -> str:
    chat_id = req.chat_id or DEFAULT_CHAT_ID
    if not chat_id:
        raise HTTPException(status_code=400, detail="chat_id is required")
    return chat_id


@app.post("/api/send", response_model=SendMessageResponse)
async def send_message(req: SendMessageRequest) -> SendMessageResponse:
    if not TELEGRAM_BOT_TOKEN:
        raise HTTPException(status_code=500, detail="TELEGRAM_BOT_TOKEN is not set")

    chat_id = _get_chat_id(req)
    payload = {"chat_id": chat_id, "text": req.message}
    if req.parse_mode:
        payload["parse_mode"] = req.parse_mode

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        async with CLIENT_SESSION.post(url, json=payload) as resp:
            resp.raise_for_status()
            data = await resp.json()
    except aiohttp.ClientError as e:
        log.warning(f"Telegram send failed: {e!r}")
        raise HTTPException(status_code=502, detail="Telegram API request failed")

    return SendMessageResponse(ok=True, telegram_response=data)


def main() -> None:
    import uvicorn

    port = get_env_int("TELEGRAM_SERVICE_PORT")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
