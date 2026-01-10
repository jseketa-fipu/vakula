from __future__ import annotations

import asyncio
import random
import logging
import os
import zlib
from contextlib import asynccontextmanager
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
STATION_LAT = os.environ.get("STATION_LAT")
STATION_LON = os.environ.get("STATION_LON")

MODULE_NAMES = ["temperature", "wind", "rain", "snow"]

@asynccontextmanager
async def lifespan(app: FastAPI):
    global STATION_ID, logger
    STATION_ID = _resolve_station_id()
    logger = make_logger(f"{STATION_NAME}#{STATION_ID}")
    logger.info(f"Station startup id={STATION_ID}")
    await notify_broker()
    register_task = asyncio.create_task(register_with_gateway_loop())
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    try:
        yield
    finally:
        for task in (register_task, heartbeat_task):
            task.cancel()
        await asyncio.gather(register_task, heartbeat_task, return_exceptions=True)


app = FastAPI(title=f"Station {STATION_NAME}", lifespan=lifespan)

STATION_ID: int | None = None
GATEWAY_REGISTERED: bool = False
logger = make_logger(STATION_NAME)


class ModuleState(BaseModel):
    health: float = 100.0
    failed: bool = False


class AdjustRequest(BaseModel):
    module: str
    amount: float
    reason: str | None = None


class StationState(BaseModel):
    station_id: int
    name: str
    lat: float | None = None
    lon: float | None = None
    modules: Dict[str, ModuleState]
    last_event: str | None = None


class BootstrapModuleState(BaseModel):
    health: float | None = None
    failed: bool | None = None


class BootstrapRequest(BaseModel):
    modules: Dict[str, BootstrapModuleState]
    last_event: str | None = None


modules: Dict[str, ModuleState] = {m: ModuleState() for m in MODULE_NAMES}
last_event: str | None = None


def _parse_optional_float(value: str | None) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except ValueError:
        logger.warning(f"Invalid float value: {value!r}")
        return None


async def notify_broker() -> None:
    global last_event, STATION_ID
    if STATION_ID is None:
        return

    payload = StationState(
        station_id=STATION_ID,
        name=STATION_NAME,
        lat=_parse_optional_float(STATION_LAT),
        lon=_parse_optional_float(STATION_LON),
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


def _resolve_station_id() -> int:
    env_id = os.environ.get("STATION_ID")
    if env_id:
        return int(env_id)
    # Stable ID so stations can appear immediately without gateway registration.
    return zlib.crc32(STATION_NAME.encode("utf-8")) & 0x7FFFFFFF


async def register_with_gateway() -> bool:
    payload = {
        "station_id": STATION_ID,
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
        gateway_id = int(data["id"])
        if STATION_ID is not None and gateway_id != STATION_ID:
            logger.warning(
                f"Gateway assigned different station_id={gateway_id} (local={STATION_ID})"
            )
        return True


async def register_with_gateway_loop() -> None:
    global GATEWAY_REGISTERED
    while True:
        try:
            ok = await register_with_gateway()
            if ok:
                GATEWAY_REGISTERED = True
                return
        except Exception as e:
            logger.warning(f"Gateway registration failed: {e!r}")
        await asyncio.sleep(3.0)


async def heartbeat_loop() -> None:
    global STATION_ID
    if STATION_ID is None:
        return

    # Stagger startup to avoid thundering-herd heartbeat bursts.
    await asyncio.sleep(random.uniform(1.0, 15.0))

    async with httpx.AsyncClient() as client:
        while True:
            try:
                if not GATEWAY_REGISTERED:
                    await asyncio.sleep(1.0)
                    continue
                r = await client.post(
                    f"{GATEWAY_URL}/api/stations/{STATION_ID}/heartbeat",
                    json={},
                    timeout=5.0,
                )
                if r.status_code == 404:
                    logger.warning("Gateway lost station registration; re-registering.")
                    await register_with_gateway()
                    continue
                r.raise_for_status()
                await notify_broker()
            except Exception as e:
                logger.warning(f"Heartbeat failed: {e!r}")
            await asyncio.sleep(10.0)


@app.get("/state", response_model=StationState)
async def get_state() -> StationState:
    assert STATION_ID is not None
    return StationState(
        station_id=STATION_ID,
        name=STATION_NAME,
        lat=_parse_optional_float(STATION_LAT),
        lon=_parse_optional_float(STATION_LON),
        modules=modules,
        last_event=last_event,
    )


@app.post("/adjust")
async def apply_adjust(req: AdjustRequest) -> dict:
    global last_event
    m = _get_module_or_404(req.module)

    old = m.health
    m.health = min(100.0, max(0.0, m.health + req.amount))
    m.failed = m.health <= 0.0

    if req.amount < 0:
        delta = abs(req.amount)
        last_event = req.reason or f"{req.module} degraded by {delta:.1f}%"
    else:
        last_event = req.reason or f"{req.module} repaired by {req.amount:.1f}%"
    logger.info(last_event + f" (health {old:.1f} -> {m.health:.1f})")

    await notify_broker()
    return {"ok": True, "health": m.health, "failed": m.failed}


@app.post("/bootstrap")
async def bootstrap(req: BootstrapRequest) -> dict:
    global last_event
    for name, incoming in req.modules.items():
        m = _get_module_or_404(name)
        if incoming.health is not None:
            m.health = max(0.0, min(100.0, incoming.health))
            if incoming.failed is None:
                m.failed = m.health <= 0.0
        if incoming.failed is not None:
            m.failed = incoming.failed

    if req.last_event:
        last_event = req.last_event

    await notify_broker()
    return {"ok": True}


def main() -> None:
    import uvicorn

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
