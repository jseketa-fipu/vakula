import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List
from contextlib import asynccontextmanager

import aiohttp
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from vakula_common.http import create_session
from vakula_common.logging import setup_logger
from vakula_common.models import StationState
from vakula_common.modules import module_name
from vakula_common.env import get_env_int, get_env_str

log = setup_logger("BROKER")

CLIENT_SESSION: aiohttp.ClientSession | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Start background broadcaster and set up shared HTTP session.
    # The broadcaster handles stale checks + WebSocket pushes.
    global CLIENT_SESSION
    CLIENT_SESSION = create_session(10)
    task = asyncio.create_task(stale_broadcast_loop())
    try:
        yield
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        if CLIENT_SESSION:
            await CLIENT_SESSION.close()


app = FastAPI(title="Vakula Broker", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


stations: Dict[int, Dict[str, Any]] = {}

state_lock = asyncio.Lock()
connections: List[WebSocket] = []
STALE_TIMEOUT = get_env_int("BROKER_STALE_SECONDS")
TELEGRAM_URL = get_env_str("TELEGRAM_URL")
ALERT_STATUSES = {"warn", "bad", "critical", "offline"}


def _evaluate_station(station: Dict[str, Any], now: datetime) -> tuple[str, str | None, int, bool]:
    # Determine a station's status based on module health and staleness.
    # Returns: status label, worst module name, worst health, is_stale.
    modules = station.get("modules", {})
    worst_health = 100
    worst_name: str | None = None
    for name, module_state in modules.items():
        health = int(module_state.get("health", 100))
        if health < worst_health:
            worst_health = health
            worst_name = name

    last_update: datetime | None = station.get("last_update")
    stale = False
    if last_update is not None:
        stale = now - last_update > timedelta(seconds=STALE_TIMEOUT)

    status = "ok"
    if stale:
        status = "offline"
    elif worst_health <= 20:
        status = "critical"
    elif worst_health <= 50:
        status = "bad"
    elif worst_health <= 80:
        status = "warn"

    return status, worst_name, worst_health, stale


async def _send_telegram_message(message: str) -> None:
    # Forward alerts to the telegram microservice.
    # This is a best-effort fire-and-forget call.
    if not TELEGRAM_URL:
        return
    payload = {"message": message}
    try:
        async with CLIENT_SESSION.post(f"{TELEGRAM_URL}/api/send", json=payload) as resp:
            resp.raise_for_status()
    except aiohttp.ClientError as e:
        log.warning(f"Failed to notify telegram: {e!r}")


def _format_alert_message(
    station: Dict[str, Any], status: str, worst_name: str | None, worst_health: int
) -> str:
    # Build a short, human-friendly alert message.
    # Used for Telegram notifications.
    name = station.get("name", f"Station {station.get('id', '?')}")
    if status == "offline":
        module_info = f"no updates for {STALE_TIMEOUT}s"
    elif worst_name:
        try:
            module_label = module_name(int(worst_name))
        except (TypeError, ValueError):
            module_label = str(worst_name)
        module_info = f"{module_label} {worst_health}%"
    else:
        module_info = "no module data"
    return f"{name}: {status.upper()} ({module_info})"


def compute_world_state() -> Dict[str, Any]:
    # Build the full state payload for the frontend.
    # Includes computed status and overall health for each station.
    now = datetime.now(timezone.utc)
    items: List[Dict[str, Any]] = []
    for station_id, station in stations.items():
        status, _, worst, stale = _evaluate_station(station, now)
        modules = station.get("modules", {})

        lat = station.get("lat")
        lon = station.get("lon")

        items.append(
            {
                "id": station_id,
                "name": station.get("name", f"Station {station_id}"),
                "lat": lat,
                "lon": lon,
                "modules": modules,
                "last_event": station.get("last_event"),
                "overall_health": 0 if stale else worst,
                "status": status,
            }
        )
    return {"stations": items}


async def broadcast_state() -> None:
    # Send the latest world state to all WebSocket clients.
    # Removes dead connections when sending fails.
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
    # Periodically recalc statuses, alert, and broadcast.
    # This handles "offline" transitions even if stations stop updating.
    while True:
        await asyncio.sleep(5)
        notify_messages: List[str] = []
        async with state_lock:
            now = datetime.now(timezone.utc)
            for station in stations.values():
                status, worst_name, worst_health, _ = _evaluate_station(station, now)
                previous_status = station.get("status")
                station["status"] = status
                if (
                    status in ALERT_STATUSES
                    and status != previous_status
                    and station.get("last_notified_status") != status
                ):
                    station["last_notified_status"] = status
                    notify_messages.append(
                        _format_alert_message(station, status, worst_name, worst_health)
                    )
        for msg in notify_messages:
            await _send_telegram_message(msg)
        await broadcast_state()


@app.post("/api/station-update")
async def station_update(update: StationState) -> Dict[str, Any]:
    # Receive a station update and update global state.
    # Also emits alerts when status crosses thresholds.
    notify_message: str | None = None
    async with state_lock:
        now = datetime.now(timezone.utc)
        station = stations.get(update.station_id)
        if not station:
            station = {"id": update.station_id, "name": update.name, "modules": {}}

        station["name"] = update.name
        station["last_update"] = now
        if update.lat is not None:
            station["lat"] = update.lat
        if update.lon is not None:
            station["lon"] = update.lon

        modules = station.setdefault("modules", {})
        for name, module_state in update.modules.items():
            modules[name] = {"health": module_state.health, "failed": module_state.failed}

        if update.last_event:
            station["last_event"] = update.last_event

        status, worst_name, worst_health, _ = _evaluate_station(station, now)
        prev_status = station.get("status")
        station["status"] = status
        if (
            status in ALERT_STATUSES
            and status != prev_status
            and station.get("last_notified_status") != status
        ):
            station["last_notified_status"] = status
            notify_message = _format_alert_message(station, status, worst_name, worst_health)

        stations[update.station_id] = station

    if notify_message:
        await _send_telegram_message(notify_message)
    await broadcast_state()
    return {"ok": True}


@app.get("/api/state")
async def get_state() -> Dict[str, Any]:
    # Return current world state snapshot.
    # Used by frontend and by the orchestrator to pick ids.
    async with state_lock:
        return compute_world_state()


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Stream state updates to the frontend in real time.
    # A fresh full-state snapshot is sent on connect.
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
    # Run the API server.
    # Starts FastAPI + WebSocket server.
    import uvicorn

    port = get_env_int("BROKER_PORT")
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
