from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class ConnectionState(str, Enum):
    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    ERROR = "error"


@dataclass(frozen=True)
class LakeShoreReading:
    channel: str | int
    resistance_ohm: float | None
    temperature_K: float | None = None
    excitation_power_W: float | None = None
    quadrature_ohm: float | None = None
    excitation_current_A: float | None = None
    raw: dict[str, Any] = field(default_factory=dict)
    status: str = "OK"


@dataclass(frozen=True)
class PPMSStatus:
    temperature_K: float | None
    temperature_status: Any
    field_T: float | None
    field_status: Any
    chamber_status: Any
    position_deg: float | None = None
    position_status: Any = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MeasurementRecord:
    timestamp_utc: datetime
    elapsed_s: float
    ppms: PPMSStatus
    lakeshore: LakeShoreReading
    resistivity_ohm_m: float | None
    resistivity_ohm_cm: float | None
    sequence_step_index: int | None
    sequence_step_name: str
    comment: str = ""
    error: str = ""

    @property
    def timestamp_iso(self) -> str:
        return self.timestamp_utc.astimezone(timezone.utc).isoformat()

    def to_multivu_columns(self) -> dict[str, object]:
        return {
            "Timestamp UTC": self.timestamp_iso,
            "Elapsed Time (s)": self.elapsed_s,
            "PPMS Temperature (K)": self.ppms.temperature_K,
            "PPMS Temperature Status": str(self.ppms.temperature_status),
            "PPMS Field (T)": self.ppms.field_T,
            "PPMS Field Status": str(self.ppms.field_status),
            "PPMS Chamber Status": str(self.ppms.chamber_status),
            "PPMS Position (deg)": self.ppms.position_deg,
            "PPMS Position Status": str(self.ppms.position_status),
            "LakeShore Channel": str(self.lakeshore.channel),
            "Resistance (Ohm)": self.lakeshore.resistance_ohm,
            "Resistivity (Ohm m)": self.resistivity_ohm_m,
            "Resistivity (Ohm cm)": self.resistivity_ohm_cm,
            "LS372 Temperature (K)": self.lakeshore.temperature_K,
            "Excitation Power (W)": self.lakeshore.excitation_power_W,
            "Excitation Current (A)": self.lakeshore.excitation_current_A,
            "Quadrature (Ohm)": self.lakeshore.quadrature_ohm,
            "Sequence Step Index": self.sequence_step_index,
            "Sequence Step Name": self.sequence_step_name,
            "Comment": self.comment,
            "Error": self.error,
        }
