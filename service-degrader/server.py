import asyncio
import os
import random

import aiohttp
from vakula_common import HttpClient, MODULE_IDS, module_name, setup_logger

log = setup_logger("DEGRADE")
HTTP_CLIENT = HttpClient()

# In Docker, this will be http://gateway:8000 (see docker-compose.yml)
GATEWAY_URL = os.environ["GATEWAY_URL"]
TICK_SECONDS = int(os.environ["TICK_SECONDS"])


async def choose_station() -> int | None:
    """
    Return a random station id, or None if:
      - no stations are registered yet, or
      - the gateway is currently unreachable.
    """
    try:
        async with HTTP_CLIENT.session.get(f"{GATEWAY_URL}/api/stations") as resp:
            resp.raise_for_status()
            stations = await resp.json()
    except aiohttp.ClientError as e:
        log.warning(f"Could not reach gateway at {GATEWAY_URL}: {e!r}")
        return None

    if not stations:
        return None

    station = random.choice(stations)
    return station["id"]


async def main() -> None:
    # Periodically degrade a random module on a random station.
    # This simulates wear and tear in the system.
    log.info(f"Starting adjust service; tick={TICK_SECONDS}s; gateway={GATEWAY_URL}")
    HTTP_CLIENT.create_session(5)
    try:
        # Small initial delay to give gateway time to bind its port (important in Docker)
        await asyncio.sleep(3)

        while True:
            station_id = await choose_station()
            if station_id is None:
                log.info("No stations available yet or gateway unreachable.")
                await asyncio.sleep(TICK_SECONDS)
                continue

            module_id = random.choice(MODULE_IDS)
            mod_name = module_name(module_id)
            amount = random.randint(2, 8)
            reason = f"{mod_name} wear –{amount}%"

            try:
                async with HTTP_CLIENT.session.post(
                    f"{GATEWAY_URL}/api/stations/{station_id}/adjust",
                    json={"module": module_id, "amount": -amount, "reason": reason},
                ) as resp:
                    resp.raise_for_status()
                log.info(f"Adjusted station {station_id}: {reason}")
            except aiohttp.ClientError as e:
                log.warning(f"Failed to adjust station {station_id}: {e!r}")

            await asyncio.sleep(TICK_SECONDS)
    finally:
        await HTTP_CLIENT.session.close()


if __name__ == "__main__":
    asyncio.run(main())
