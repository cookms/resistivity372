from __future__ import annotations

from typing import Protocol

from resistivity372.core.exceptions import InstrumentError


class PositionAdapter(Protocol):
    def read_position_deg(self) -> float | None: ...
    def set_position_deg(self, position_deg: float, rate_deg_per_s: float) -> None: ...


class DisabledPositionAdapter:
    def read_position_deg(self) -> float | None:
        return None

    def set_position_deg(self, position_deg: float, rate_deg_per_s: float) -> None:
        raise InstrumentError("Position control is disabled or unavailable.")


class PPMSPositionAdapter:
    def __init__(self, ppms):
        self.ppms = ppms

    def read_position_deg(self) -> float | None:
        return self.ppms.read_status().position_deg

    def set_position_deg(self, position_deg: float, rate_deg_per_s: float) -> None:
        self.ppms.set_position(position_deg, rate_deg_per_s)
