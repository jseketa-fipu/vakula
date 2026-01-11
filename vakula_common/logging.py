import logging
from typing import Any, MutableMapping, Tuple


def setup_logger(prefix: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format=f"[{prefix}] %(message)s")
    return logging.getLogger(__name__)


def make_logger(
    base_logger: logging.Logger,
    name: str,
) -> logging.LoggerAdapter[logging.Logger]:
    class StationAdapter(logging.LoggerAdapter[logging.Logger]):
        def process(
            self, msg: str, kwargs: MutableMapping[str, Any]
        ) -> Tuple[str, MutableMapping[str, Any]]:
            kwargs.setdefault("extra", {})
            kwargs["extra"]["station"] = name
            return msg, kwargs

    return StationAdapter(base_logger, {})
