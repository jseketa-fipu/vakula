import aiohttp


def create_session(timeout_seconds: int) -> aiohttp.ClientSession:
    timeout = aiohttp.ClientTimeout(total=timeout_seconds)
    return aiohttp.ClientSession(timeout=timeout)
