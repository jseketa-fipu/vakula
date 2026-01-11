import logging


def setup_logger(prefix: str) -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format=f"[{prefix}] %(message)s")
    return logging.getLogger(__name__)


def make_logger(base_logger: logging.Logger, name: str) -> logging.LoggerAdapter:
    class StationAdapter(logging.LoggerAdapter):
        def process(self, msg, kwargs):
            kwargs.setdefault("extra", {})
            kwargs["extra"]["station"] = name
            return msg, kwargs

    return StationAdapter(base_logger, {})
