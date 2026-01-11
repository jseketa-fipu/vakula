import os


def get_env_str(name: str) -> str:
    return os.environ[name]


def get_env_int(name: str) -> int:
    return int(os.environ[name])


def get_env_optional_float(name: str) -> float | None:
    value = os.environ.get(name, "")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None
