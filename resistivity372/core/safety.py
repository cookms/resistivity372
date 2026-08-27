from __future__ import annotations

from dataclasses import dataclass

from .exceptions import SafetyLimitError


@dataclass(frozen=True)
class SafetyLimits:
    temperature_min_K: float = 1.8
    temperature_max_K: float = 400.0
    temperature_rate_max_K_per_min: float = 10.0

    field_abs_max_T: float = 9.0
    field_rate_max_T_per_min: float = 0.2

    allowed_chamber_modes: tuple[str, ...] = (
        "seal",
        "purge_seal",
        "vent_seal",
        "pump_continuous",
        "vent_continuous",
        "high_vacuum",
    )

    position_min_deg: float = -360.0
    position_max_deg: float = 360.0
    position_rate_max_deg_per_s: float = 10.0

    def check_temperature(self, setpoint_K: float, rate_K_per_min: float) -> None:
        if not self.temperature_min_K <= setpoint_K <= self.temperature_max_K:
            raise SafetyLimitError(
                f"Temperature setpoint {setpoint_K:g} K is outside "
                f"{self.temperature_min_K:g} to {self.temperature_max_K:g} K."
            )
        if abs(rate_K_per_min) > self.temperature_rate_max_K_per_min:
            raise SafetyLimitError(
                f"Temperature ramp {rate_K_per_min:g} K/min exceeds "
                f"{self.temperature_rate_max_K_per_min:g} K/min."
            )

    def check_field(self, setpoint_T: float, rate_T_per_min: float) -> None:
        if abs(setpoint_T) > self.field_abs_max_T:
            raise SafetyLimitError(
                f"Field setpoint {setpoint_T:g} T exceeds +/-{self.field_abs_max_T:g} T."
            )
        if abs(rate_T_per_min) > self.field_rate_max_T_per_min:
            raise SafetyLimitError(
                f"Field ramp {rate_T_per_min:g} T/min exceeds "
                f"{self.field_rate_max_T_per_min:g} T/min."
            )

    def check_chamber(self, mode: str) -> None:
        if mode not in self.allowed_chamber_modes:
            raise SafetyLimitError(f"Chamber mode {mode!r} is not allowed by configuration.")

    def check_position(self, position_deg: float, rate_deg_per_s: float) -> None:
        if not self.position_min_deg <= position_deg <= self.position_max_deg:
            raise SafetyLimitError(
                f"Position {position_deg:g} deg is outside "
                f"{self.position_min_deg:g} to {self.position_max_deg:g} deg."
            )
        if abs(rate_deg_per_s) > self.position_rate_max_deg_per_s:
            raise SafetyLimitError(
                f"Position rate {rate_deg_per_s:g} deg/s exceeds "
                f"{self.position_rate_max_deg_per_s:g} deg/s."
            )


def safety_from_config(config: dict) -> SafetyLimits:
    cfg = dict(config.get("safety", {}))
    if "allowed_chamber_modes" in cfg and isinstance(cfg["allowed_chamber_modes"], list):
        cfg["allowed_chamber_modes"] = tuple(cfg["allowed_chamber_modes"])
    return SafetyLimits(**cfg)
