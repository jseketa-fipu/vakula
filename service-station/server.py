import asyncio
import random
import os
from contextlib import asynccontextmanager
from typing import Dict

import aiohttp
import uvicorn
from fastapi import FastAPI, HTTPException
from vakula_common.http import create_session
from vakula_common.logging import make_logger, setup_logger
from vakula_common.models import AdjustRequest, ModuleState, StationState
from vakula_common.modules import MODULE_IDS, module_name

log = setup_logger("STATION")


GATEWAY_URL = os.environ["GATEWAY_URL"]
BROKER_URL = os.environ["BROKER_URL"]
STATION_NAME = os.environ["STATION_NAME"]
PUBLIC_BASE_URL = os.environ["PUBLIC_BASE_URL"]
PORT = int(os.environ["PORT"])
_lat = os.environ.get("STATION_LAT")
_lon = os.environ.get("STATION_LON")
STATION_LAT = float(_lat) if _lat else None
STATION_LON = float(_lon) if _lon else None

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize station state and background tasks on startup.
    # Lifespan runs once on startup and once on shutdown.
    global STATION_ID, logger, CLIENT_SESSION
    STATION_ID = _resolve_station_id()
    logger = make_logger(log, f"{STATION_NAME}#{STATION_ID}")
    logger.info(f"Station startup id={STATION_ID}")
    CLIENT_SESSION = create_session(5)
    await notify_broker()
    register_task = asyncio.create_task(register_with_gateway_loop())
    heartbeat_task = asyncio.create_task(heartbeat_loop())
    try:
        yield
    finally:
        for task in (register_task, heartbeat_task):
            task.cancel()
        await asyncio.gather(register_task, heartbeat_task, return_exceptions=True)
        if CLIENT_SESSION:
            await CLIENT_SESSION.close()


app = FastAPI(title=f"Station {STATION_NAME}", lifespan=lifespan)

STATION_ID: int | None = None
GATEWAY_REGISTERED: bool = False
logger = make_logger(log, STATION_NAME)
CLIENT_SESSION: aiohttp.ClientSession | None = None


modules: Dict[int, ModuleState] = {module_id: ModuleState() for module_id in MODULE_IDS}
last_event: str | None = None


async def notify_broker() -> None:
    # Push the latest station state to the broker.
    # The broker then broadcasts this to the frontend.
    global last_event, STATION_ID
    if STATION_ID is None:
        return

    payload = _build_station_state().model_dump()

    try:
        async with CLIENT_SESSION.post(
            f"{BROKER_URL}/api/station-update",
            json=payload,
        ) as resp:
            resp.raise_for_status()
    except Exception as e:
        logger.warning(f"Failed to notify broker: {e!r}")


def _get_module_or_404(module_id: int) -> ModuleState:
    # Validate module id and return its state.
    # Prevents accidental updates to unknown modules.
    if module_id not in modules:
        raise HTTPException(status_code=404, detail=f"Unknown module id {module_id}")
    return modules[module_id]




def _resolve_station_id() -> int:
    # Read station id from environment.
    # Orchestrator sets this when it creates a container.
    return int(os.environ["STATION_ID"])


def _build_station_state() -> StationState:
    # Build the current station snapshot.
    # Used for both broker updates and the /state endpoint.
    assert STATION_ID is not None
    return StationState(
        station_id=STATION_ID,
        name=STATION_NAME,
        lat=STATION_LAT,
        lon=STATION_LON,
        modules=modules,
        last_event=last_event,
    )




async def register_with_gateway() -> bool:
    # Register this station with the gateway.
    # The gateway keeps the registry and liveness info.
    payload = {
        "station_id": STATION_ID,
        "name": STATION_NAME,
        "base_url": PUBLIC_BASE_URL,
    }
    async with CLIENT_SESSION.post(
        f"{GATEWAY_URL}/api/register",
        json=payload,
    ) as resp:
        resp.raise_for_status()
        data = await resp.json()
    gateway_id = int(data["id"])
    if STATION_ID is not None and gateway_id != STATION_ID:
        logger.warning(
            f"Gateway assigned different station_id={gateway_id} (local={STATION_ID})"
        )
    return True


async def register_with_gateway_loop() -> None:
    # Keep retrying registration until it succeeds.
    # Useful during startup when other services may not be ready yet.
    global GATEWAY_REGISTERED
    while True:
        try:
            ok = await register_with_gateway()
            if ok:
                GATEWAY_REGISTERED = True
                return
        except Exception as e:
            logger.warning(f"Gateway registration failed: {e!r}")
        await asyncio.sleep(3)


async def heartbeat_loop() -> None:
    # Periodically send heartbeat and updates to the gateway.
    # This is how the gateway knows the station is alive.
    global STATION_ID
    if STATION_ID is None:
        return

    # Stagger startup to avoid thundering-herd heartbeat bursts.
    await asyncio.sleep(random.randint(1, 15))

    while True:
        try:
            if not GATEWAY_REGISTERED:
                await asyncio.sleep(1)
                continue
            async with CLIENT_SESSION.post(
                f"{GATEWAY_URL}/api/stations/{STATION_ID}/heartbeat",
                json={},
            ) as resp:
                if resp.status == 404:
                    logger.warning("Gateway lost station registration; re-registering.")
                    await register_with_gateway()
                    continue
                resp.raise_for_status()
            await notify_broker()
        except Exception as e:
            logger.warning(f"Heartbeat failed: {e!r}")
        await asyncio.sleep(10)


@app.get("/state", response_model=StationState)
async def get_state() -> StationState:
    # Return the current station state.
    # Handy for debugging a single station directly.
    return _build_station_state()


@app.post("/adjust")
async def apply_adjust(request: AdjustRequest) -> dict:
    # Apply a health change to a single module.
    # Health is clamped to 0..100 and failed is derived from 0.
    global last_event
    module_state = _get_module_or_404(request.module)

    previous_health = module_state.health
    module_state.health = min(100, max(0, module_state.health + request.amount))
    module_state.failed = module_state.health <= 0

    module_name_text = module_name(request.module)
    if request.amount < 0:
        delta = abs(request.amount)
        last_event = request.reason or f"{module_name_text} degraded by {delta}%"
    else:
        last_event = request.reason or f"{module_name_text} repaired by {request.amount}%"
    logger.info(last_event + f" (health {previous_health} -> {module_state.health})")

    await notify_broker()
    return {"ok": True, "health": module_state.health, "failed": module_state.failed}


def main() -> None:
    # Run the API server.
    # Station containers call this on startup.
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        reload=False,
    )


if __name__ == "__main__":
    main()
