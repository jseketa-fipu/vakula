from typing import Dict

from pydantic import BaseModel


class ModuleState(BaseModel):
    health: int = 100
    failed: bool = False


class AdjustRequest(BaseModel):
    module: int
    amount: int
    reason: str | None = None


class StationState(BaseModel):
    station_id: int
    name: str
    lat: float | None = None
    lon: float | None = None
    modules: Dict[int, ModuleState]
    last_event: str | None = None

