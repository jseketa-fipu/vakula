from __future__ import annotations

import asyncio
import logging
import os
from typing import Dict

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(
    level=logging.INFO,
    format="[STATION] %(message)s",  # only standard fields: no %(station_name)s etc.
)
log = logging.getLogger(__name__)


def make_logger(station_name: str):
    class StationAdapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            kwargs.setdefault("extra", {})
            kwargs["extra"]["station"] = station_name
            return msg, kwargs

    return StationAdapter(log, {})


GATEWAY_URL = os.environ.get("GATEWAY_URL", "http://gateway:8000")
BROKER_URL = os.environ.get("BROKER_URL", "http://broker:8001")
STATION_NAME = os.environ.get("STATION_NAME", "Unnamed station")
PUBLIC_BASE_URL = os.environ.get("PUBLIC_BASE_URL", "http://station:9000")
PORT = int(os.environ.get("PORT", "9000"))

MODULE_NAMES = ["temperature", "wind", "rain", "snow"]

app = FastAPI(title=f"Station {STATION_NAME}")

STATION_ID: int | None = None
logger = make_logger(STATION_NAME)


class ModuleState(BaseModel):
    health: float = 100.0
    failed: bool = False


class DegradeRequest(BaseModel):
    module: str
    amount: float
    reason: str | None = None


class RepairRequest(BaseModel):
    module: str
    amount: float
    reason: str | None = None


class StationState(BaseModel):
    station_id: int
    name: str
    modules: Dict[str, ModuleState]
    last_event: str | None = None


modules: Dict[str, ModuleState] = {m: ModuleState() for m in MODULE_NAMES}
last_event: str | None = None


async def notify_broker() -> None:
    global last_event, STATION_ID
    if STATION_ID is None:
        return

    payload = StationState(
        station_id=STATION_ID,
        name=STATION_NAME,
        modules=modules,
        last_event=last_event,
    ).model_dump()

    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{BROKER_URL}/api/station-update",
                json=payload,
                timeout=5.0,
            )
            r.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to notify broker: {e!r}")


def _get_module_or_404(name: str) -> ModuleState:
    if name not in modules:
        raise HTTPException(status_code=404, detail=f"Unknown module {name}")
    return modules[name]


async def register_with_gateway() -> int:
    payload = {
        "name": STATION_NAME,
        "base_url": PUBLIC_BASE_URL,
        "tags": [],
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{GATEWAY_URL}/api/register",
            json=payload,
            timeout=5.0,
        )
        r.raise_for_status()
        data = r.json()
        return int(data["id"])


async def heartbeat_loop() -> None:
    global STATION_ID
    if STATION_ID is None:
        return

    async with httpx.AsyncClient() as client:
        while True:
            try:
                await client.post(
                    f"{GATEWAY_URL}/api/stations/{STATION_ID}/heartbeat",
                    json={},
                    timeout=5.0,
                )
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e!r}")
            await asyncio.sleep(10.0)


@app.get("/state", response_model=StationState)
async def get_state() -> StationState:
    assert STATION_ID is not None
    return StationState(
        station_id=STATION_ID,
        name=STATION_NAME,
        modules=modules,
        last_event=last_event,
    )


@app.post("/degrade")
async def apply_degrade(req: DegradeRequest) -> dict:
    global last_event
    m = _get_module_or_404(req.module)

    old = m.health
    m.health = max(0.0, m.health - req.amount)
    m.failed = m.health <= 0.0

    last_event = req.reason or f"{req.module} degraded by {req.amount:.1f}%"
    logger.info(last_event + f" (health {old:.1f} -> {m.health:.1f})")

    await notify_broker()
    return {"ok": True, "health": m.health, "failed": m.failed}


@app.post("/repair")
async def apply_repair(req: RepairRequest) -> dict:
    global last_event
    m = _get_module_or_404(req.module)

    old = m.health
    m.health = min(100.0, m.health + req.amount)
    if m.health > 0:
        m.failed = False

    last_event = req.reason or f"{req.module} repaired by {req.amount:.1f}%"
    logger.info(last_event + f" (health {old:.1f} -> {m.health:.1f})")

    await notify_broker()
    return {"ok": True, "health": m.health, "failed": m.failed}


@app.on_event("startup")
async def on_startup() -> None:
    global STATION_ID, logger
    STATION_ID = await register_with_gateway()
    logger = make_logger(f"{STATION_NAME}#{STATION_ID}")
    logger.info(f"Registered with gateway as station_id={STATION_ID}")
    # Push initial state so the broker can show stations before any events.
    await notify_broker()
    asyncio.create_task(heartbeat_loop())


def main() -> None:
    import uvicorn

    uvicorn.run(
        "vakula.station_service:app",
        host="0.0.0.0",
        port=PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
