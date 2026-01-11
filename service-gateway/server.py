from datetime import datetime, timedelta, timezone
from typing import Dict, List

import os
import uvicorn
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from contextlib import asynccontextmanager
from vakula_common import AdjustRequest, HttpClient, create_session, setup_logger

log = setup_logger("GATEWAY")
HTTP_CLIENT = HttpClient()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create one shared HTTP session for all outbound calls.
    # This keeps connections reused and avoids per-request session overhead.
    HTTP_CLIENT.session = create_session(5)
    try:
        yield
    finally:
        await HTTP_CLIENT.session.close()


app = FastAPI(title="Vakula Gateway / Registrar", lifespan=lifespan)


class RegistrationRequest(BaseModel):
    station_id: int | None = None
    name: str
    base_url: str


class StationInfo(BaseModel):
    id: int
    name: str
    base_url: str
    last_heartbeat: datetime


class Heartbeat(BaseModel):
    pass


class AdjustCommand(AdjustRequest):
    pass


STATIONS: Dict[int, StationInfo] = {}
NEXT_ID: int = 0

HEARTBEAT_TIMEOUT = int(os.environ["HEARTBEAT_TIMEOUT_SECONDS"])


def _get_station_or_404(station_id: int) -> StationInfo:
    # Helper: return station or fail fast if it doesn't exist.
    # Keeps the endpoints small and consistent.
    station = STATIONS.get(station_id)
    if not station:
        raise HTTPException(status_code=404, detail="Unknown station id")
    return station


@app.post("/api/register", response_model=StationInfo)
def register_station(request: RegistrationRequest) -> StationInfo:
    # Register a station or update it if the same id already exists.
    # Station IDs are assigned by the gateway unless the station asks for one.
    global NEXT_ID
    station_id = request.station_id if request.station_id is not None else NEXT_ID
    if request.station_id is None:
        NEXT_ID += 1
    else:
        existing = STATIONS.get(station_id)
        if existing:
            existing.name = request.name
            existing.base_url = request.base_url
            existing.last_heartbeat = datetime.now(timezone.utc)
            log.info(f"Updated station {station_id}: {existing.name} @ {existing.base_url}")
            return existing
        if station_id >= NEXT_ID:
            NEXT_ID = station_id + 1

    info = StationInfo(
        id=station_id,
        name=request.name,
        base_url=request.base_url,
        last_heartbeat=datetime.now(timezone.utc),
    )
    STATIONS[station_id] = info
    log.info(f"Registered station {station_id}: {info.name} @ {info.base_url}")
    return info


@app.post("/api/stations/{station_id}/heartbeat")
def heartbeat(station_id: int, hb: Heartbeat) -> dict:
    # Mark station as alive by updating its last heartbeat time.
    # Broker uses this to filter out offline stations.
    station = _get_station_or_404(station_id)
    station.last_heartbeat = datetime.now(timezone.utc)
    return {"ok": True}


@app.get("/api/stations", response_model=List[StationInfo])
def list_stations() -> List[StationInfo]:
    # Return only stations with recent heartbeats.
    # This list is used by the degrader and orchestrator.
    now = datetime.now(timezone.utc)
    alive: List[StationInfo] = []
    for station in STATIONS.values():
        if now - station.last_heartbeat <= timedelta(seconds=HEARTBEAT_TIMEOUT):
            alive.append(station)
    return alive


@app.get("/api/stations/{station_id}", response_model=StationInfo)
def get_station(station_id: int) -> StationInfo:
    # Fetch a single station's info.
    # Used for debugging and possible admin tooling.
    return _get_station_or_404(station_id)


async def _forward_to_station(station: StationInfo, path: str, payload: dict) -> dict:
    # Send a command to the station's own API.
    # This keeps clients from needing the station URL directly.
    url = f"{station.base_url}{path}"
    async with HTTP_CLIENT.session.post(url, json=payload) as resp:
        resp.raise_for_status()
        return await resp.json()


@app.post("/api/stations/{station_id}/adjust")
async def gateway_adjust(station_id: int, cmd: AdjustCommand) -> dict:
    # Forward an adjust command to the correct station.
    # Errors here are translated into a 502 for upstream clients.
    station = _get_station_or_404(station_id)
    direction = "repair" if cmd.amount >= 0 else "degrade"
    log.info(
        f"Forwarding {direction} to station {station_id} ({station.name}): "
        f"{cmd.module} {cmd.amount:+d}%"
    )
    try:
        result = await _forward_to_station(station, "/adjust", cmd.model_dump())
        return {"ok": True, "station_id": station_id, "station_response": result}
    except Exception as e:
        log.warning(f"Failed to forward adjust to station {station_id}: {e!r}")
        raise HTTPException(status_code=502, detail="Station unreachable")


def main() -> None:
    # Run the API server.
    # Uvicorn handles FastAPI's async app.
    port = int(os.environ["GATEWAY_PORT"])
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
