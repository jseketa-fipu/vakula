import asyncio
import random

import aiohttp
from vakula_common.modules import MODULE_IDS, module_name
from vakula_common.http import create_session
from vakula_common.logging import setup_logger
from vakula_common.env import get_env_int, get_env_str

log = setup_logger("DEGRADE")

# In Docker, this will be http://gateway:8000 (see docker-compose.yml)
GATEWAY_URL = get_env_str("GATEWAY_URL")
TICK_SECONDS = get_env_int("TICK_SECONDS")


async def choose_station(client: aiohttp.ClientSession) -> int | None:
    """
    Return a random station id, or None if:
      - no stations are registered yet, or
      - the gateway is currently unreachable.
    """
    try:
        async with client.get(f"{GATEWAY_URL}/api/stations") as resp:
            resp.raise_for_status()
            stations = await resp.json()
    except aiohttp.ClientError as e:
        log.warning(f"Could not reach gateway at {GATEWAY_URL}: {e!r}")
        return None

    if not stations:
        return None

    st = random.choice(stations)
    return st["id"]


async def main() -> None:
    log.info(f"Starting adjust service; tick={TICK_SECONDS}s; gateway={GATEWAY_URL}")
    async with create_session(5) as client:
        # Small initial delay to give gateway time to bind its port (important in Docker)
        await asyncio.sleep(3)

        while True:
            station_id = await choose_station(client)
            if station_id is None:
                log.info("No stations available yet or gateway unreachable.")
                await asyncio.sleep(TICK_SECONDS)
                continue

            module_id = random.choice(MODULE_IDS)
            mod_name = module_name(module_id)
            amount = random.randint(2, 8)
            reason = f"{mod_name} wear –{amount}%"

            try:
                async with client.post(
                    f"{GATEWAY_URL}/api/stations/{station_id}/adjust",
                    json={"module": module_id, "amount": -amount, "reason": reason},
                ) as resp:
                    resp.raise_for_status()
                log.info(f"Adjusted station {station_id}: {reason}")
            except aiohttp.ClientError as e:
                log.warning(f"Failed to adjust station {station_id}: {e!r}")

            await asyncio.sleep(TICK_SECONDS)


if __name__ == "__main__":
    asyncio.run(main())
