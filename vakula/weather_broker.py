from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="[BROKER] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Vakula Broker")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class BrokerModuleState(BaseModel):
    health: float
    failed: bool = False


class StationUpdate(BaseModel):
    station_id: int
    name: str
    modules: Dict[str, BrokerModuleState]
    last_event: str | None = None


stations: Dict[int, Dict[str, Any]] = {}
station_meta_by_name: Dict[str, Dict[str, float]] = {}

state_lock = asyncio.Lock()
connections: List[WebSocket] = []


def load_station_meta() -> None:
    global station_meta_by_name
    data_path = Path(__file__).parent / "data" / "croatia_stations.json"
    if not data_path.exists():
        log.warning("croatia_stations.json not found; map will have no coordinates")
        station_meta_by_name = {}
        return
    data = json.loads(data_path.read_text(encoding="utf-8"))
    station_meta_by_name = {item["name"]: {"lat": item["lat"], "lon": item["lon"]} for item in data}
    log.info(f"Loaded {len(station_meta_by_name)} station metadata entries")


def compute_world_state() -> Dict[str, Any]:
    items: List[Dict[str, Any]] = []
    for sid, st in stations.items():
        modules = st.get("modules", {})
        worst = 100.0
        if modules:
            worst = min((m["health"] for m in modules.values()), default=100.0)

        status = "ok"
        if worst <= 20.0:
            status = "critical"
        elif worst <= 50.0:
            status = "bad"
        elif worst <= 80.0:
            status = "warn"

        meta = station_meta_by_name.get(st.get("name", ""))
        lat = st.get("lat", meta["lat"] if meta else None)
        lon = st.get("lon", meta["lon"] if meta else None)

        items.append(
            {
                "id": sid,
                "name": st.get("name", f"Station {sid}"),
                "lat": lat,
                "lon": lon,
                "modules": modules,
                "last_event": st.get("last_event"),
                "overall_health": worst,
                "status": status,
            }
        )
    return {"stations": items}


async def broadcast_state() -> None:
    if not connections:
        return
    state = compute_world_state()
    dead: List[WebSocket] = []
    for ws in list(connections):
        try:
            await ws.send_text(json.dumps(state))
        except Exception:
            dead.append(ws)
    for ws in dead:
        try:
            connections.remove(ws)
        except ValueError:
            pass


@app.post("/api/station-update")
async def station_update(update: StationUpdate) -> Dict[str, Any]:
    async with state_lock:
        st = stations.get(update.station_id)
        if not st:
            st = {"id": update.station_id, "name": update.name, "modules": {}}
            meta = station_meta_by_name.get(update.name)
            if meta:
                st["lat"] = meta["lat"]
                st["lon"] = meta["lon"]
            stations[update.station_id] = st
        else:
            st["name"] = update.name

        modules = st.setdefault("modules", {})
        for name, m in update.modules.items():
            modules[name] = {"health": m.health, "failed": m.failed}

        if update.last_event:
            st["last_event"] = update.last_event

    await broadcast_state()
    return {"ok": True}


@app.get("/api/state")
async def get_state() -> Dict[str, Any]:
    async with state_lock:
        return compute_world_state()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    connections.append(websocket)
    try:
        async with state_lock:
            await websocket.send_text(json.dumps(compute_world_state()))
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    except Exception:
        pass
    finally:
        try:
            connections.remove(websocket)
        except ValueError:
            pass


@app.on_event("startup")
async def on_startup() -> None:
    load_station_meta()


def main() -> None:
    import uvicorn

    port = int(os.environ.get("BROKER_PORT", "8001"))
    uvicorn.run(
        "vakula.weather_broker:app",
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
