from __future__ import annotations

import asyncio
import logging
import os
import random

import httpx

logging.basicConfig(level=logging.INFO, format="[DEGRADE] %(message)s")
log = logging.getLogger(__name__)

# In Docker, this will be http://gateway:8000 (see docker-compose.yml)
GATEWAY_URL = os.environ["GATEWAY_URL"]
TICK_SECONDS = float(os.environ["TICK_SECONDS"])

MODULES = ["temperature", "wind", "rain", "snow"]


async def choose_station(client: httpx.AsyncClient) -> int | None:
    """
    Return a random station id, or None if:
      - no stations are registered yet, or
      - the gateway is currently unreachable.
    """
    try:
        r = await client.get(f"{GATEWAY_URL}/api/stations", timeout=5.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        log.warning(f"Could not reach gateway at {GATEWAY_URL}: {e!r}")
        return None

    stations = r.json()
    if not stations:
        return None

    st = random.choice(stations)
    return st["id"]


async def main() -> None:
    log.info(f"Starting adjust service; tick={TICK_SECONDS}s; gateway={GATEWAY_URL}")
    async with httpx.AsyncClient() as client:
        # Small initial delay to give gateway time to bind its port (important in Docker)
        await asyncio.sleep(3.0)

        while True:
            station_id = await choose_station(client)
            if station_id is None:
                log.info("No stations available yet or gateway unreachable.")
                await asyncio.sleep(TICK_SECONDS)
                continue

            module = random.choice(MODULES)
            amount = random.uniform(2.0, 8.0)
            reason = f"{module} wear –{amount:.1f}%"

            try:
                r = await client.post(
                    f"{GATEWAY_URL}/api/stations/{station_id}/adjust",
                    json={"module": module, "amount": -amount, "reason": reason},
                    timeout=5.0,
                )
                r.raise_for_status()
                log.info(f"Adjusted station {station_id}: {reason}")
            except httpx.HTTPError as e:
                log.warning(f"Failed to adjust station {station_id}: {e!r}")

            await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
