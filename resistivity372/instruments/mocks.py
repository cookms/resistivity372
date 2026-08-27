from __future__ import annotations

import math
import random
import time
from typing import Any

from resistivity372.core.exceptions import InstrumentConnectionError
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
    def __init__(self, safety: SafetyLimits | None = None):
        self.safety = safety or SafetyLimits()
        self._connected = False
        self.temperature_K = 300.0
        self.field_T = 0.0
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
        return PPMSStatus(
            temperature_K=self.temperature_K,
            temperature_status="stable",
            field_T=self.field_T,
            field_status="stable",
            chamber_status=self.chamber_status,
            position_deg=self.position_deg,
            position_status="stable" if self.position_deg is not None else None,
            raw={"simulated": True},
        )

    def set_temperature(self, setpoint_K: float, rate_K_per_min: float, approach: str = "fast_settle") -> None:
        self._require_connected()
        self.safety.check_temperature(setpoint_K, rate_K_per_min)
        self.temperature_K = float(setpoint_K)

    def set_field(
        self,
        setpoint_T: float,
        rate_T_per_min: float,
        approach: str = "linear",
        driven_mode: str | None = None,
    ) -> None:
        self._require_connected()
        self.safety.check_field(setpoint_T, rate_T_per_min)
        self.field_T = float(setpoint_T)

    def set_chamber(self, mode_name: str) -> None:
        self._require_connected()
        self.safety.check_chamber(mode_name)
        self.chamber_status = mode_name

    def set_position(self, position_deg: float, rate_deg_per_s: float) -> None:
        self._require_connected()
        self.safety.check_position(position_deg, rate_deg_per_s)
        self.position_deg = float(position_deg)

    def wait_until_steady(
        self,
        targets: tuple[str, ...],
        timeout_s: float,
        settle_s: float,
        abort_flag,
        poll_s: float = 2.0,
    ) -> None:
        self._require_connected()
        deadline = time.monotonic() + min(settle_s, timeout_s)
        while time.monotonic() < deadline:
            if abort_flag.is_set():
                return
            time.sleep(min(0.02, deadline - time.monotonic()))

    def _require_connected(self) -> None:
        if not self._connected:
            raise InstrumentConnectionError("Mock PPMS is not connected.")
