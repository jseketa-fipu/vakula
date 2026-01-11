import aiohttp


class HttpClient:
    session: aiohttp.ClientSession

    def create_session(self, timeout_seconds: int) -> None:
        timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self.session = aiohttp.ClientSession(timeout=timeout)
