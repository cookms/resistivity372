from __future__ import annotations

import math
import random
import time
from typing import Any

from resistivity372.core.exceptions import (
    InstrumentConnectionError,
    InstrumentError,
    InstrumentTimeoutError,
)
from resistivity372.core.models import LakeShoreReading, PPMSStatus
from resistivity372.core.safety import SafetyLimits


class MockLakeShore372Controller:
    def __init__(self, base_resistance_ohm: float = 100.0, noise_ohm: float = 0.01):
        self.base = base_resistance_ohm
        self.noise = noise_ohm
        self._connected = False
        self._t0 = time.monotonic()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def configure_channel(self, channel: int | str, settings: dict[str, Any]) -> None:
        self._require_connected()

    def read_channel(self, channel: int | str) -> LakeShoreReading:
        self._require_connected()
        t = time.monotonic() - self._t0
        r = self.base * (1.0 + 0.002 * math.sin(t / 20.0)) + random.gauss(0.0, self.noise)
        return LakeShoreReading(
            channel=channel,
            resistance_ohm=r,
            temperature_K=None,
            excitation_power_W=1e-12,
            quadrature_ohm=random.gauss(0.0, self.noise / 10.0),
            status="SIMULATED",
        )

    def metadata(self) -> dict[str, Any]:
        return {"driver": "mock", "model": "LS372", "connected": self._connected}

    def _require_connected(self) -> None:
        if not self._connected:
            raise InstrumentConnectionError("Mock Lake Shore 372 is not connected.")


class MockPPMSController:
    def __init__(self, safety: SafetyLimits | None = None, ramp_readings: int = 0):
        self.safety = safety or SafetyLimits()
        self.ramp_readings = max(0, int(ramp_readings))
        self._connected = False
        self.temperature_K = 300.0
        self.field_T = 0.0
        self._temperature_target_K = self.temperature_K
        self._field_target_T = self.field_T
        self._temperature_increment_K = 0.0
        self._field_increment_T = 0.0
        self._temperature_remaining = 0
        self._field_remaining = 0
        self.chamber_status = "sealed"
        self.position_deg: float | None = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._connected = True

    def disconnect(self) -> None:
        self._connected = False

    def read_status(self) -> PPMSStatus:
        self._require_connected()
        self._advance_ramps()
        return PPMSStatus(
            temperature_K=self.temperature_K,
            temperature_status="ramping" if self._temperature_remaining else "stable",
            field_T=self.field_T,
            field_status="ramping" if self._field_remaining else "stable",
            chamber_status=self.chamber_status,
            position_deg=self.position_deg,
            position_status="stable" if self.position_deg is not None else None,
            raw={"simulated": True},
        )

    def set_temperature(
        self, setpoint_K: float, rate_K_per_min: float, approach: str = "fast_settle"
    ) -> None:
        self._require_connected()
        self.safety.check_temperature(setpoint_K, rate_K_per_min)
        self._temperature_target_K = float(setpoint_K)
        if self.ramp_readings:
            self._temperature_remaining = self.ramp_readings
            self._temperature_increment_K = (
                self._temperature_target_K - self.temperature_K
            ) / self.ramp_readings
        else:
            self.temperature_K = self._temperature_target_K
            self._temperature_remaining = 0

    def set_field(
        self,
        setpoint_T: float,
        rate_T_per_min: float,
        approach: str = "linear",
        driven_mode: str | None = None,
    ) -> None:
        self._require_connected()
        self.safety.check_field(setpoint_T, rate_T_per_min)
        self._field_target_T = float(setpoint_T)
        if self.ramp_readings:
            self._field_remaining = self.ramp_readings
            self._field_increment_T = (self._field_target_T - self.field_T) / self.ramp_readings
        else:
            self.field_T = self._field_target_T
            self._field_remaining = 0

    def set_chamber(self, mode_name: str) -> None:
        self._require_connected()
        self.safety.check_chamber(mode_name)
        self.chamber_status = mode_name

    def set_position(self, position_deg: float, rate_deg_per_s: float) -> None:
        self._require_connected()
        self.safety.check_position(position_deg, rate_deg_per_s)
        self.position_deg = float(position_deg)

    def wait_for_temperature(
        self,
        target_K: float,
        tolerance_K: float,
        stable_s: float,
        equilibration_s: float,
        timeout_s: float,
        abort_flag,
        poll_s: float = 2.0,
    ) -> None:
        self._wait_for_condition(
            lambda: abs(self.temperature_K - target_K) <= tolerance_K,
            "temperature",
            stable_s,
            equilibration_s,
            timeout_s,
            abort_flag,
        )

    def wait_for_field(
        self,
        target_T: float,
        tolerance_T: float,
        stable_s: float,
        equilibration_s: float,
        timeout_s: float,
        abort_flag,
        poll_s: float = 2.0,
        read_delay_s: float | None = None,
    ) -> None:
        self._wait_for_condition(
            lambda: abs(self.field_T - target_T) <= tolerance_T,
            "field",
            stable_s,
            equilibration_s,
            timeout_s,
            abort_flag,
        )

    def wait_for_chamber(
        self,
        target_mode: str,
        stable_s: float,
        equilibration_s: float,
        timeout_s: float,
        abort_flag,
        poll_s: float = 2.0,
    ) -> None:
        self._wait_for_condition(
            lambda: self.chamber_status == target_mode,
            "chamber",
            stable_s,
            equilibration_s,
            timeout_s,
            abort_flag,
        )

    def _wait_for_condition(
        self,
        condition,
        description: str,
        stable_s: float,
        equilibration_s: float,
        timeout_s: float,
        abort_flag,
    ) -> None:
        self._require_connected()
        deadline = time.monotonic() + timeout_s
        stable_since: float | None = None
        while True:
            if abort_flag.is_set():
                raise InstrumentError("Wait aborted by user.")
            now = time.monotonic()
            if now > deadline:
                raise InstrumentTimeoutError(
                    f"Mock PPMS did not reach stable {description} within {timeout_s:g} s."
                )
            self._advance_ramps()
            if condition():
                stable_since = stable_since if stable_since is not None else now
                if now - stable_since >= stable_s:
                    break
            else:
                stable_since = None
            time.sleep(0.001)

        equilibration_deadline = time.monotonic() + equilibration_s
        while time.monotonic() < equilibration_deadline:
            if abort_flag.is_set():
                raise InstrumentError("Wait aborted by user.")
            time.sleep(min(0.02, equilibration_deadline - time.monotonic()))

    def _advance_ramps(self) -> None:
        if self._temperature_remaining:
            self._temperature_remaining -= 1
            self.temperature_K += self._temperature_increment_K
            if not self._temperature_remaining:
                self.temperature_K = self._temperature_target_K
        if self._field_remaining:
            self._field_remaining -= 1
            self.field_T += self._field_increment_T
            if not self._field_remaining:
                self.field_T = self._field_target_T

    def _require_connected(self) -> None:
        if not self._connected:
            raise InstrumentConnectionError("Mock PPMS is not connected.")
