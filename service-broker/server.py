from __future__ import annotations

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="[BROKER] %(message)s")
log = logging.getLogger(__name__)

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_station_meta()
    task = asyncio.create_task(stale_broadcast_loop())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


app = FastAPI(title="Vakula Broker", lifespan=lifespan)

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
    lat: float | None = None
    lon: float | None = None
    modules: Dict[str, BrokerModuleState]
    last_event: str | None = None


stations: Dict[int, Dict[str, Any]] = {}
station_meta_by_name: Dict[str, Dict[str, float]] = {}

state_lock = asyncio.Lock()
connections: List[WebSocket] = []
STALE_TIMEOUT = int(os.environ["BROKER_STALE_SECONDS"])
TELEGRAM_URL = os.environ["TELEGRAM_URL"]
ALERT_STATUSES = {"warn", "bad", "critical", "offline"}


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


def _evaluate_station(st: Dict[str, Any], now: datetime) -> tuple[str, str | None, float, bool]:
    modules = st.get("modules", {})
    worst_health = 100.0
    worst_name: str | None = None
    for name, mod in modules.items():
        health = float(mod.get("health", 100.0))
        if health < worst_health:
            worst_health = health
            worst_name = name

    last_update: datetime | None = st.get("last_update")
    stale = False
    if last_update is not None:
        stale = now - last_update > timedelta(seconds=STALE_TIMEOUT)

    status = "ok"
    if stale:
        status = "offline"
    elif worst_health <= 20.0:
        status = "critical"
    elif worst_health <= 50.0:
        status = "bad"
    elif worst_health <= 80.0:
        status = "warn"

    return status, worst_name, worst_health, stale


async def _send_telegram_message(message: str) -> None:
    if not TELEGRAM_URL:
        return
    payload = {"message": message}
    try:
        async with httpx.AsyncClient() as client:
            r = await client.post(f"{TELEGRAM_URL}/api/send", json=payload, timeout=10.0)
            r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning(f"Failed to notify telegram: {e!r}")


def _format_alert_message(
    st: Dict[str, Any], status: str, worst_name: str | None, worst_health: float
) -> str:
    name = st.get("name", f"Station {st.get('id', '?')}")
    if status == "offline":
        module_info = f"no updates for {STALE_TIMEOUT}s"
    elif worst_name:
        module_info = f"{worst_name} {worst_health:.1f}%"
    else:
        module_info = "no module data"
    return f"{name}: {status.upper()} ({module_info})"


def compute_world_state() -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    items: List[Dict[str, Any]] = []
    for sid, st in stations.items():
        status, _, worst, stale = _evaluate_station(st, now)
        modules = st.get("modules", {})

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
                "overall_health": 0.0 if stale else worst,
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


async def stale_broadcast_loop() -> None:
    while True:
        await asyncio.sleep(5.0)
        notify_messages: List[str] = []
        async with state_lock:
            now = datetime.now(timezone.utc)
            for st in stations.values():
                status, worst_name, worst_health, _ = _evaluate_station(st, now)
                prev_status = st.get("status")
                st["status"] = status
                if (
                    status in ALERT_STATUSES
                    and status != prev_status
                    and st.get("last_notified_status") != status
                ):
                    st["last_notified_status"] = status
                    notify_messages.append(
                        _format_alert_message(st, status, worst_name, worst_health)
                    )
        for msg in notify_messages:
            await _send_telegram_message(msg)
        await broadcast_state()


@app.post("/api/station-update")
async def station_update(update: StationUpdate) -> Dict[str, Any]:
    notify_message: str | None = None
    async with state_lock:
        now = datetime.now(timezone.utc)
        st = stations.get(update.station_id)
        if not st:
            st = {"id": update.station_id, "name": update.name, "modules": {}}
            meta = station_meta_by_name.get(update.name)
        else:
            meta = None

        st["name"] = update.name
        st["last_update"] = now
        if meta:
            st["lat"] = meta["lat"]
            st["lon"] = meta["lon"]
        if update.lat is not None:
            st["lat"] = update.lat
        if update.lon is not None:
            st["lon"] = update.lon

        modules = st.setdefault("modules", {})
        for name, m in update.modules.items():
            modules[name] = {"health": m.health, "failed": m.failed}

        if update.last_event:
            st["last_event"] = update.last_event

        status, worst_name, worst_health, _ = _evaluate_station(st, now)
        prev_status = st.get("status")
        st["status"] = status
        if (
            status in ALERT_STATUSES
            and status != prev_status
            and st.get("last_notified_status") != status
        ):
            st["last_notified_status"] = status
            notify_message = _format_alert_message(st, status, worst_name, worst_health)

        stations[update.station_id] = st

    if notify_message:
        await _send_telegram_message(notify_message)
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


def main() -> None:
    import uvicorn

    port = int(os.environ["BROKER_PORT"])
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
