# Vakula microservices sandbox (Docker-ready)

This project simulates Croatian weather stations as microservices:

- **gateway_service** (`vakula/gateway_service.py`)
  - API gateway / registrar for stations
  - Stations register on startup and send heartbeats
  - Degrade / repair commands are forwarded via the gateway

- **station_service** (`vakula/station_service.py`)
  - One instance per *physical* station (40 Croatian stations)
  - Keeps per-module health (temperature / wind / rain / snow)
  - Accepts `/degrade` and `/repair` commands
  - Pushes its current state to the broker

- **weather_broker** (`vakula/weather_broker.py`)
  - Central world state for the frontend
  - Receives `/api/station-update` from stations
  - Broadcasts the full map state to the frontend over WebSocket `/ws`

- **degrade_service** (`vakula/degrade_service.py`)
  - **Separate microservice** that periodically picks a random registered
    station and module and issues a degrade command *via the gateway*.

- **frontend** (`frontend/index.html`)
  - Leaflet-based map of Croatia with stations colour-coded by health
  - Connects to the broker WebSocket on `ws://<host>:8001/ws`

## Run everything with one Docker command

You need **Docker** and **docker compose**.

1. Build and start all services:

```bash
docker compose up --build
```

This will start:
- `gateway` on port **8000**
- `broker` on port **8001**
- `degrader` (no exposed port)
- `frontend` on port **8080**
- One container per Croatian station: `station_Bilogora`, `station_Bjelovar`, ...

2. Open the frontend in your browser:

```text
http://localhost:8080/index.html
```

The page will connect to the broker at `ws://localhost:8001/ws`.
You should see:

- A map of Croatia with markers for all stations (using their real lat/lon)
- Marker colour shows worst module health:
  - green: > 80%
  - yellow: > 50%
  - orange: > 20%
  - red: <= 20%
- A sidebar with station list and module health
- A small event log of the last events

The **degrader** service runs independently and continuously degrades
random modules at random stations via the gateway.

To stop everything:

```bash
docker compose down
```

## Notes

- All internal service discovery uses Docker's default network:
  - `gateway` is reachable as `http://gateway:8000`
  - `broker` as `http://broker:8001`
  - Each station container as `http://station_<Name>:9000`
- No database is used; everything is in memory.
- For local non-Docker development you can still run the services via
  `python -m vakula.<service>` if you set the appropriate env vars
  (`GATEWAY_URL`, `BROKER_URL`, etc.).
