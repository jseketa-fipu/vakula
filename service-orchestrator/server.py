from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import unicodedata
import zlib
from typing import Any, Dict, List

import httpx
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="[ORCH] %(message)s")
log = logging.getLogger(__name__)

app = FastAPI(title="Vakula Station Orchestrator")

DOCKER_SOCKET = os.environ["DOCKER_SOCKET"]
DOCKER_API_VERSION = os.environ["DOCKER_API_VERSION"]
GATEWAY_URL = os.environ["GATEWAY_URL"]
BROKER_URL = os.environ["BROKER_URL"]
STATION_IMAGE = os.environ["STATION_IMAGE"]
ORCHESTRATOR_NETWORK = os.environ["ORCHESTRATOR_NETWORK"]


class ModuleState(BaseModel):
    health: float | None = None
    failed: bool | None = None


class CreateStationRequest(BaseModel):
    station_id: int | None = None
    name: str
    lat: float
    lon: float
    modules: Dict[str, ModuleState] | None = None
    tags: List[str] | None = None


class CreateStationResponse(BaseModel):
    ok: bool
    container_id: str
    container_name: str


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii")
    ascii_value = ascii_value.lower()
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-")
    return ascii_value


def _docker_client() -> httpx.AsyncClient:
    transport = httpx.AsyncHTTPTransport(uds=DOCKER_SOCKET)
    return httpx.AsyncClient(transport=transport, base_url="http://docker")


async def _next_station_id(fallback_name: str) -> int:
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(f"{BROKER_URL}/api/state", timeout=5.0)
            r.raise_for_status()
            stations = r.json().get("stations", [])
            if stations:
                ids = [int(st["id"]) for st in stations if "id" in st]
                if ids:
                    return max(ids) + 1
        except Exception as e:
            log.warning(f"Failed to fetch stations from broker: {e!r}")

        try:
            r = await client.get(f"{GATEWAY_URL}/api/stations", timeout=5.0)
            r.raise_for_status()
            stations = r.json()
            if stations:
                ids = [int(st["id"]) for st in stations if "id" in st]
                if ids:
                    return max(ids) + 1
        except Exception as e:
            log.warning(f"Failed to fetch stations from gateway: {e!r}")

        return abs(zlib.crc32(fallback_name.encode("utf-8")) & 0x7FFFFFFF)


def _default_modules() -> Dict[str, ModuleState]:
    names = ["temperature", "wind", "rain", "snow"]
    return {name: ModuleState(health=100.0, failed=False) for name in names}

async def _docker_request(
    method: str, path: str, *, params: dict | None = None, json_body: dict | None = None
) -> httpx.Response:
    versions = [DOCKER_API_VERSION, "v1.44", "v1.45", "v1.46"]
    seen = set()
    last_response: httpx.Response | None = None
    async with _docker_client() as client:
        for version in versions:
            if not version or version in seen:
                continue
            seen.add(version)
            url = f"/{version}{path}"
            r = await client.request(method, url, params=params, json=json_body)
            last_response = r
            if r.status_code != 400:
                return r
            if "too old" not in r.text:
                return r
    assert last_response is not None
    return last_response


async def _find_compose_container(service_name: str) -> Dict[str, Any]:
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
    r = await _docker_request("GET", f"/containers/{container_id}/json")
    r.raise_for_status()
    return r.json()


def _pick_network(inspect: Dict[str, Any]) -> str:
    if ORCHESTRATOR_NETWORK:
        return ORCHESTRATOR_NETWORK
    networks = inspect.get("NetworkSettings", {}).get("Networks", {})
    if networks:
        return next(iter(networks.keys()))
    return "bridge"


async def _docker_create_container(payload: Dict[str, Any], name: str) -> httpx.Response:
    return await _docker_request(
        "POST",
        "/containers/create",
        params={"name": name},
        json_body=payload,
    )


async def _docker_start_container(container_id: str) -> None:
    r = await _docker_request("POST", f"/containers/{container_id}/start")
    r.raise_for_status()


async def _docker_remove_container(container_name: str) -> None:
    r = await _docker_request(
        "DELETE",
        f"/containers/{container_name}",
        params={"force": "true"},
    )
    if r.status_code not in {204, 404}:
        r.raise_for_status()


async def _bootstrap_station(base_url: str, modules: Dict[str, ModuleState]) -> None:
    payload = {
        "modules": {k: v.model_dump(exclude_none=True) for k, v in modules.items()}
    }
    async with httpx.AsyncClient() as client:
        for _ in range(12):
            try:
                r = await client.post(f"{base_url}/bootstrap", json=payload, timeout=5.0)
                r.raise_for_status()
                return
            except Exception:
                await asyncio.sleep(1.0)
    raise HTTPException(status_code=502, detail="Station did not respond to bootstrap")


async def _create_station(req: CreateStationRequest) -> CreateStationResponse:
    gateway_container = await _find_compose_container("gateway")
    gateway_inspect = await _inspect_container(gateway_container["Id"])
    network_name = _pick_network(gateway_inspect)
    image_name = STATION_IMAGE or gateway_inspect.get("Config", {}).get("Image", "")
    if not image_name:
        raise HTTPException(status_code=500, detail="Could not resolve station image")

    station_id = req.station_id
    if station_id is None:
        station_id = await _next_station_id(req.name)

    slug = _slugify(req.name)
    if not slug:
        slug = f"station-{station_id}"
    base_name = f"station-{slug}"
    base_env = [
        f"GATEWAY_URL={GATEWAY_URL}",
        f"BROKER_URL={BROKER_URL}",
        f"STATION_NAME={req.name}",
        f"STATION_ID={station_id}",
        f"STATION_LAT={req.lat}",
        f"STATION_LON={req.lon}",
        "PORT=9000",
    ]
    modules = req.modules or _default_modules()

    container_id: str | None = None
    container_name: str | None = None
    base_url: str | None = None
    last_conflict: httpx.Response | None = None
    for attempt in range(10):
        container_name = base_name if attempt == 0 else f"{base_name}-{attempt}"
        base_url = f"http://{container_name}:9000"
        env = [*base_env, f"PUBLIC_BASE_URL={base_url}"]
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
    await _bootstrap_station(base_url, modules)

    return CreateStationResponse(ok=True, container_id=container_id, container_name=container_name)


@app.post("/api/stations", response_model=List[CreateStationResponse])
async def create_station(
    reqs: List[CreateStationRequest],
) -> List[CreateStationResponse]:
    results: List[CreateStationResponse] = []
    for req in reqs:
        results.append(await _create_station(req))
    return results


def main() -> None:
    import uvicorn

    port = int(os.environ["ORCHESTRATOR_PORT"])
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    main()
