from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import os

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, AnyUrl

logging.basicConfig(level=logging.INFO, format="[GATEWAY] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Vakula Gateway / Registrar")


class RegistrationRequest(BaseModel):
    station_id: int | None = None
    name: str
    base_url: str
    tags: List[str] = []


class StationInfo(BaseModel):
    id: int
    name: str
    base_url: str
    tags: List[str]
    last_heartbeat: datetime


class Heartbeat(BaseModel):
    pass


class AdjustCommand(BaseModel):
    module: str
    amount: float
    reason: str | None = None


STATIONS: Dict[int, StationInfo] = {}
NEXT_ID: int = 0

HEARTBEAT_TIMEOUT = int(os.environ["HEARTBEAT_TIMEOUT_SECONDS"])


def _get_station_or_404(station_id: int) -> StationInfo:
    st = STATIONS.get(station_id)
    if not st:
        raise HTTPException(status_code=404, detail="Unknown station id")
    return st


@app.post("/api/register", response_model=StationInfo)
def register_station(req: RegistrationRequest) -> StationInfo:
    global NEXT_ID
    station_id = req.station_id if req.station_id is not None else NEXT_ID
    if req.station_id is None:
        NEXT_ID += 1
    else:
        existing = STATIONS.get(station_id)
        if existing:
            existing.name = req.name
            existing.base_url = req.base_url
            existing.tags = req.tags
            existing.last_heartbeat = datetime.now(timezone.utc)
            log.info(f"Updated station {station_id}: {existing.name} @ {existing.base_url}")
            return existing
        if station_id >= NEXT_ID:
            NEXT_ID = station_id + 1

    info = StationInfo(
        id=station_id,
        name=req.name,
        base_url=req.base_url,
        tags=req.tags,
        last_heartbeat=datetime.now(timezone.utc),
    )
    STATIONS[station_id] = info
    log.info(f"Registered station {station_id}: {info.name} @ {info.base_url}")
    return info


@app.post("/api/stations/{station_id}/heartbeat")
def heartbeat(station_id: int, hb: Heartbeat) -> dict:
    st = _get_station_or_404(station_id)
    st.last_heartbeat = datetime.now(timezone.utc)
    return {"ok": True}


@app.get("/api/stations", response_model=List[StationInfo])
def list_stations() -> List[StationInfo]:
    now = datetime.now(timezone.utc)
    alive: List[StationInfo] = []
    for st in STATIONS.values():
        if now - st.last_heartbeat <= timedelta(seconds=HEARTBEAT_TIMEOUT):
            alive.append(st)
    return alive


@app.get("/api/stations/{station_id}", response_model=StationInfo)
def get_station(station_id: int) -> StationInfo:
    return _get_station_or_404(station_id)


async def _forward_to_station(station: StationInfo, path: str, payload: dict) -> dict:
    url = f"{station.base_url}{path}"
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, timeout=5.0)
        r.raise_for_status()
        return r.json()


@app.post("/api/stations/{station_id}/adjust")
async def gateway_adjust(station_id: int, cmd: AdjustCommand) -> dict:
    st = _get_station_or_404(station_id)
    direction = "repair" if cmd.amount >= 0 else "degrade"
    log.info(
        f"Forwarding {direction} to station {station_id} ({st.name}): "
        f"{cmd.module} {cmd.amount:+.1f}%"
    )
    try:
        result = await _forward_to_station(st, "/adjust", cmd.model_dump())
        return {"ok": True, "station_id": station_id, "station_response": result}
    except Exception as e:
        log.warning(f"Failed to forward adjust to station {station_id}: {e!r}")
        raise HTTPException(status_code=502, detail="Station unreachable")


def main() -> None:
    import uvicorn

    port = int(os.environ["GATEWAY_PORT"])
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
