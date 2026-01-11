MODULES: dict[int, str] = {
    1: "temperature",
    2: "wind",
    3: "rain",
    4: "snow",
}

MODULE_IDS: list[int] = list(MODULES.keys())


def module_name(module_id: int) -> str:
    return MODULES.get(module_id, f"module-{module_id}")
