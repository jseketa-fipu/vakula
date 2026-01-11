import asyncio
import json
import os
import re
import unicodedata
from typing import Any, Dict, List

import aiohttp
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, confloat
from vakula_common.http import create_session
from vakula_common.logging import setup_logger

log = setup_logger("ORCH")

CLIENT_SESSION: aiohttp.ClientSession | None = None
DOCKER_SESSION: aiohttp.ClientSession | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create shared sessions for HTTP and Docker socket calls.
    # This avoids reconnect overhead for every request and keeps it centralized.
    global CLIENT_SESSION, DOCKER_SESSION
    CLIENT_SESSION = create_session(5)
    connector = aiohttp.UnixConnector(path=DOCKER_SOCKET)
    DOCKER_SESSION = aiohttp.ClientSession(connector=connector, base_url="http://docker")
    try:
        yield
    finally:
        if CLIENT_SESSION:
            await CLIENT_SESSION.close()
        if DOCKER_SESSION:
            await DOCKER_SESSION.close()


app = FastAPI(title="Vakula Station Orchestrator", lifespan=lifespan)

DOCKER_SOCKET = os.environ["DOCKER_SOCKET"]
DOCKER_API_VERSION = os.environ["DOCKER_API_VERSION"]
GATEWAY_URL = os.environ["GATEWAY_URL"]
BROKER_URL = os.environ["BROKER_URL"]
STATION_IMAGE = os.environ.get("STATION_IMAGE", "")
ORCHESTRATOR_NETWORK = os.environ["ORCHESTRATOR_NETWORK"]


class CreateStationRequest(BaseModel):
    station_id: int | None = None
    name: str
    lat: confloat(ge=-90, le=90)
    lon: confloat(ge=-180, le=180)


class CreateStationResponse(BaseModel):
    ok: bool
    container_id: str
    container_name: str


class SimpleResponse:
    def __init__(self, status_code: int, text: str, json_data: Any):
        self.status_code = status_code
        self.text = text
        self._json_data = json_data

    def json(self) -> Any:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"Docker API error {self.status_code}: {self.text}")


def _slugify(value: str) -> str:
    # Turn a station name into a Docker-friendly container name.
    # We normalize accents and replace non-alphanumerics with dashes.
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return ascii_value


async def _next_station_id() -> int:
    # Pick the next free station id based on broker/gateway state.
    # Broker is preferred (has full state), gateway is fallback.
    try:
        async with CLIENT_SESSION.get(f"{BROKER_URL}/api/state") as resp:
            resp.raise_for_status()
            data = await resp.json()
            stations = data.get("stations", [])
        if stations:
            ids = [int(station["id"]) for station in stations if "id" in station]
            if ids:
                return max(ids) + 1
    except Exception as e:
        log.warning(f"Failed to fetch stations from broker: {e!r}")

    try:
        async with CLIENT_SESSION.get(f"{GATEWAY_URL}/api/stations") as resp:
            resp.raise_for_status()
            stations = await resp.json()
        if stations:
            ids = [int(station["id"]) for station in stations if "id" in station]
            if ids:
                return max(ids) + 1
    except Exception as e:
        log.warning(f"Failed to fetch stations from gateway: {e!r}")

    return 1000


async def _station_exists(name: str, lat: float, lon: float) -> bool:
    # Check if a station with same name/coords already exists.
    # This prevents duplicates stacking on the same map location.
    try:
        async with CLIENT_SESSION.get(f"{BROKER_URL}/api/state") as resp:
            resp.raise_for_status()
            data = await resp.json()
            stations = data.get("stations", [])
        for station in stations:
            if (
                station.get("name") == name
                and station.get("lat") == lat
                and station.get("lon") == lon
            ):
                return True
    except Exception as e:
        log.warning(f"Failed to check existing stations: {e!r}")
    return False

async def _docker_request(
    method: str, path: str, *, params: dict | None = None, json_body: dict | None = None
) -> SimpleResponse:
    # Low-level helper for Docker HTTP API calls.
    # It tries multiple API versions for compatibility.
    versions = [DOCKER_API_VERSION, "v1.44", "v1.45", "v1.46"]
    seen = set()
    last_response: SimpleResponse | None = None
    for version in versions:
        if not version or version in seen:
            continue
        seen.add(version)
        url = f"/{version}{path}"
        async with DOCKER_SESSION.request(method, url, params=params, json=json_body) as resp:
            text = await resp.text()
            try:
                data = json.loads(text) if text else None
            except json.JSONDecodeError:
                data = None
            r = SimpleResponse(resp.status, text, data)
        last_response = r
        if r.status_code != 400:
            return r
        if "too old" not in r.text:
            return r
    assert last_response is not None
    return last_response


async def _find_compose_container(service_name: str) -> Dict[str, Any]:
    # Find a running compose container by service name.
    # We search by Docker labels first, then fall back to name scanning.
    filters = {"label": [f"com.docker.compose.service={service_name}"]}
    r = await _docker_request(
        "GET",
        "/containers/json",
        params={"filters": json.dumps(filters)},
    )
    if r.status_code == 400:
        log.warning(f"Docker filters rejected; falling back to name scan: {r.text}")
        r = await _docker_request("GET", "/containers/json")
    r.raise_for_status()
    containers = r.json()

    if not containers:
        raise HTTPException(status_code=502, detail=f"No container found for {service_name}")

    for container in containers:
        labels = container.get("Labels", {})
        if labels.get("com.docker.compose.service") == service_name:
            return container

    for container in containers:
        for name in container.get("Names", []):
            if service_name in name:
                return container

    raise HTTPException(status_code=502, detail=f"No container found for {service_name}")


async def _inspect_container(container_id: str) -> Dict[str, Any]:
    # Read container details from Docker.
    # Used to discover the network and image used by the gateway.
    r = await _docker_request("GET", f"/containers/{container_id}/json")
    r.raise_for_status()
    return r.json()


def _pick_network(inspect: Dict[str, Any]) -> str:
    # Use the same Docker network as the gateway.
    # This ensures services can reach each other by container name.
    if ORCHESTRATOR_NETWORK:
        return ORCHESTRATOR_NETWORK
    networks = inspect.get("NetworkSettings", {}).get("Networks", {})
    if networks:
        return next(iter(networks.keys()))
    return "bridge"


async def _docker_create_container(payload: Dict[str, Any], name: str) -> SimpleResponse:
    # Create a container with a given name and payload.
    # This is the Docker equivalent of "docker run".
    return await _docker_request(
        "POST",
        "/containers/create",
        params={"name": name},
        json_body=payload,
    )


async def _docker_start_container(container_id: str) -> None:
    # Start a container by id.
    # Equivalent to "docker start".
    r = await _docker_request("POST", f"/containers/{container_id}/start")
    r.raise_for_status()


async def _docker_remove_container(container_name: str) -> None:
    # Remove a container by name (force).
    # Used when a name conflict happens on creation.
    r = await _docker_request(
        "DELETE",
        f"/containers/{container_name}",
        params={"force": "true"},
    )
    if r.status_code not in {204, 404}:
        r.raise_for_status()


async def _create_station(request: CreateStationRequest) -> CreateStationResponse:
    # Create and start a new station container.
    # Steps: find gateway container -> pick network -> create station container.
    if await _station_exists(request.name, request.lat, request.lon):
        raise HTTPException(
            status_code=409,
            detail="Station with same name and coordinates already exists",
        )
    gateway_container = await _find_compose_container("gateway")
    gateway_inspect = await _inspect_container(gateway_container["Id"])
    network_name = _pick_network(gateway_inspect)
    image_name = STATION_IMAGE or gateway_inspect.get("Config", {}).get("Image", "")
    if not image_name:
        raise HTTPException(status_code=500, detail="Could not resolve station image")

    station_id = request.station_id
    if station_id is None:
        station_id = await _next_station_id()

    slug = _slugify(request.name)
    if not slug:
        slug = f"station-{station_id}"
    base_name = f"station-{slug}"
    base_env = [
        f"GATEWAY_URL={GATEWAY_URL}",
        f"BROKER_URL={BROKER_URL}",
        f"STATION_NAME={request.name}",
        f"STATION_ID={station_id}",
        f"STATION_LAT={request.lat}",
        f"STATION_LON={request.lon}",
        "PORT=9000",
    ]
    container_id: str | None = None
    container_name: str | None = None
    base_url: str | None = None
    last_conflict: SimpleResponse | None = None
    for attempt in range(10):
        container_name = base_name if attempt == 0 else f"{base_name}-{attempt}"
        base_url = f"http://{container_name}:9000"
        env = [
            *base_env,
            f"PUBLIC_BASE_URL={base_url}",
        ]
        payload = {
            "Image": image_name,
            "Cmd": ["python", "/app/service-station/server.py"],
            "Env": env,
            "ExposedPorts": {"9000/tcp": {}},
            "HostConfig": {
                "NetworkMode": network_name,
                "RestartPolicy": {"Name": "unless-stopped"},
            },
        }

        r = await _docker_create_container(payload, container_name)
        if r.status_code == 409:
            await _docker_remove_container(container_name)
            r = await _docker_create_container(payload, container_name)
            if r.status_code == 409:
                last_conflict = r
                continue
            r.raise_for_status()
            container_id = r.json()["Id"]
            break
        r.raise_for_status()
        container_id = r.json()["Id"]
        break

    if container_id is None or container_name is None or base_url is None:
        detail = "Container name already exists."
        if last_conflict is not None:
            detail = f"Container name conflict: {last_conflict.text}"
        raise HTTPException(status_code=409, detail=detail)

    await _docker_start_container(container_id)

    return CreateStationResponse(ok=True, container_id=container_id, container_name=container_name)


@app.post("/api/stations", response_model=List[CreateStationResponse])
async def create_station(
    requests: List[CreateStationRequest],
) -> List[CreateStationResponse]:
    # Create one or more stations in a single request.
    # If station_id is missing, we auto-assign sequential ids.
    results: List[CreateStationResponse] = []
    next_id: int | None = None
    for request in requests:
        if request.station_id is None:
            if next_id is None:
                next_id = await _next_station_id()
            request = request.model_copy(update={"station_id": next_id})
            next_id += 1
        results.append(await _create_station(request))
    return results


def main() -> None:
    # Run the API server.
    # Uvicorn handles the async event loop and HTTP server.
    port = int(os.environ["ORCHESTRATOR_PORT"])
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
