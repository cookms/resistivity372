from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Protocol

from resistivity372.core.exceptions import (
    InstrumentConnectionError,
    InstrumentError,
    InstrumentTimeoutError,
)
from resistivity372.core.models import PPMSStatus
from resistivity372.core.safety import SafetyLimits

log = logging.getLogger(__name__)

OE_PER_TESLA = 10_000.0


class PPMSInterface(Protocol):
    @property
    def is_connected(self) -> bool: ...
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def read_status(self) -> PPMSStatus: ...
    def set_temperature(self, setpoint_K: float, rate_K_per_min: float, approach: str = "fast_settle") -> None: ...
    def set_field(self, setpoint_T: float, rate_T_per_min: float, approach: str = "linear", driven_mode: str | None = None) -> None: ...
    def set_chamber(self, mode_name: str) -> None: ...
    def set_position(self, position_deg: float, rate_deg_per_s: float) -> None: ...
    def wait_until_steady(self, targets: tuple[str, ...], timeout_s: float, settle_s: float, abort_flag, poll_s: float = 2.0) -> None: ...


@dataclass(frozen=True)
class PPMSConfig:
    host: str = "127.0.0.1"
    port: int = 5000
    socket_timeout_s: float | None = 10.0
    platform: str = "ppms"
    use_position: bool = False

    @classmethod
    def from_config(cls, config: dict) -> "PPMSConfig":
        c = config.get("ppms", {})
        return cls(
            host=c.get("host", "127.0.0.1"),
            port=int(c.get("port", 5000)),
            socket_timeout_s=c.get("socket_timeout_s", 10.0),
            platform=c.get("platform", "ppms"),
            use_position=bool(c.get("use_position", False)),
        )


class RealPPMSController:
    """PPMS/MultiVu wrapper using MultiPyVu.Client.

    The app exposes field in tesla. MultiPyVu field commands use Oe internally, so conversion
    happens only at this controller boundary.
    """

    def __init__(self, config: PPMSConfig, safety: SafetyLimits, dry_run: bool = False):
        self.config = config
        self.safety = safety
        self.dry_run = dry_run
        self._client = None
        self._mpv = None
        self._connected = False
        self._lock = threading.RLock()

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        with self._lock:
            try:
                import MultiPyVu as mpv

                self._mpv = mpv
                kwargs: dict[str, Any] = {"host": self.config.host, "port": self.config.port}
                if self.config.socket_timeout_s is not None:
                    kwargs["socket_timeout"] = self.config.socket_timeout_s
                try:
                    self._client = mpv.Client(**kwargs)
                except TypeError:
                    kwargs.pop("socket_timeout", None)
                    self._client = mpv.Client(**kwargs)
                self._client.open()
                self._connected = True
                log.info("Connected to MultiPyVu server at %s:%s", self.config.host, self.config.port)
            except Exception as exc:
                self._client = None
                self._connected = False
                raise InstrumentConnectionError(
                    f"Could not connect to MultiPyVu server: {exc}"
                ) from exc

    def disconnect(self) -> None:
        with self._lock:
            try:
                if self._client is not None and hasattr(self._client, "close_client"):
                    self._client.close_client()
            except Exception:
                log.exception("Error while disconnecting MultiPyVu client.")
            finally:
                self._client = None
                self._connected = False

    def read_status(self) -> PPMSStatus:
        with self._lock:
            c = self._require_connected()
            try:
                temp_K, temp_status = c.get_temperature()
                field_oe, field_status = c.get_field()
                chamber_status = c.get_chamber()
                pos = None
                pos_status = None
                if self.config.use_position and hasattr(c, "get_position"):
                    try:
                        pos, pos_status = c.get_position()
                    except Exception as exc:
                        pos_status = f"position unavailable: {exc}"
                return PPMSStatus(
                    temperature_K=_safe_float(temp_K),
                    temperature_status=temp_status,
                    field_T=_safe_float(field_oe) / OE_PER_TESLA if field_oe is not None else None,
                    field_status=field_status,
                    chamber_status=chamber_status,
                    position_deg=_safe_float(pos),
                    position_status=pos_status,
                    raw={
                        "temperature_status": temp_status,
                        "field_status": field_status,
                        "chamber_status": chamber_status,
                        "position_status": pos_status,
                    },
                )
            except Exception as exc:
                raise InstrumentError(f"PPMS status read failed: {exc}") from exc

    def set_temperature(self, setpoint_K: float, rate_K_per_min: float, approach: str = "fast_settle") -> None:
        self.safety.check_temperature(setpoint_K, rate_K_per_min)
        if self.dry_run:
            log.info("DRY-RUN: set_temperature(%s K, %s K/min, %s)", setpoint_K, rate_K_per_min, approach)
            return
        with self._lock:
            c = self._require_connected()
            try:
                mode = _resolve_enum(c.temperature.approach_mode, approach)
                c.set_temperature(setpoint_K, rate_K_per_min, mode)
            except Exception as exc:
                raise InstrumentError(f"PPMS set_temperature failed: {exc}") from exc

    def set_field(
        self,
        setpoint_T: float,
        rate_T_per_min: float,
        approach: str = "linear",
        driven_mode: str | None = None,
    ) -> None:
        self.safety.check_field(setpoint_T, rate_T_per_min)
        setpoint_oe = setpoint_T * OE_PER_TESLA
        rate_oe_per_s = abs(rate_T_per_min) * OE_PER_TESLA / 60.0
        if self.dry_run:
            log.info(
                "DRY-RUN: set_field(%s T, %s T/min, approach=%s, driven_mode=%s)",
                setpoint_T,
                rate_T_per_min,
                approach,
                driven_mode,
            )
            return
        with self._lock:
            c = self._require_connected()
            try:
                approach_mode = _resolve_enum(c.field.approach_mode, approach)
                if driven_mode:
                    driven = _resolve_enum(c.field.driven_mode, driven_mode)
                    c.set_field(setpoint_oe, rate_oe_per_s, approach_mode, driven)
                else:
                    c.set_field(setpoint_oe, rate_oe_per_s, approach_mode)
            except Exception as exc:
                raise InstrumentError(f"PPMS set_field failed: {exc}") from exc

    def set_chamber(self, mode_name: str) -> None:
        self.safety.check_chamber(mode_name)
        if self.dry_run:
            log.info("DRY-RUN: set_chamber(%s)", mode_name)
            return
        with self._lock:
            c = self._require_connected()
            try:
                mode = _resolve_enum(c.chamber.mode, mode_name)
                c.set_chamber(mode)
            except Exception as exc:
                raise InstrumentError(f"PPMS set_chamber failed: {exc}") from exc

    def set_position(self, position_deg: float, rate_deg_per_s: float) -> None:
        self.safety.check_position(position_deg, rate_deg_per_s)
        if self.dry_run:
            log.info("DRY-RUN: set_position(%s deg, %s deg/s)", position_deg, rate_deg_per_s)
            return
        with self._lock:
            c = self._require_connected()
            if not hasattr(c, "set_position"):
                raise InstrumentError("MultiPyVu position control is not available.")
            try:
                c.set_position(position_deg, rate_deg_per_s)
            except Exception as exc:
                raise InstrumentError(f"PPMS set_position failed: {exc}") from exc

    def wait_until_steady(
        self,
        targets: tuple[str, ...],
        timeout_s: float,
        settle_s: float,
        abort_flag,
        poll_s: float = 2.0,
    ) -> None:
        if self.dry_run:
            log.info("DRY-RUN: wait_until_steady(%s)", ",".join(targets))
            return
        with self._lock:
            c = self._require_connected()
            mask = 0
            if "temperature" in targets:
                mask |= c.temperature.waitfor
            if "field" in targets:
                mask |= c.field.waitfor
            if "chamber" in targets:
                mask |= c.chamber.waitfor

        deadline = time.monotonic() + timeout_s
        steady_since: float | None = None
        while True:
            if abort_flag.is_set():
                raise InstrumentError("Wait aborted by user.")
            if time.monotonic() > deadline:
                raise InstrumentTimeoutError(f"PPMS did not become steady within {timeout_s:g} s.")
            with self._lock:
                is_steady = c.is_steady(mask)
            now = time.monotonic()
            if is_steady:
                if steady_since is None:
                    steady_since = now
                if now - steady_since >= settle_s:
                    return
            else:
                steady_since = None
            time.sleep(poll_s)

    def _require_connected(self):
        if not self._connected or self._client is None:
            raise InstrumentConnectionError("PPMS/MultiPyVu client is not connected.")
        return self._client


def _resolve_enum(enum_container, name: str):
    """Resolve MultiPyVu enum names in a tolerant but explicit way."""
    if hasattr(enum_container, name):
        return getattr(enum_container, name)
    if hasattr(enum_container, name.upper()):
        return getattr(enum_container, name.upper())
    if hasattr(enum_container, name.lower()):
        return getattr(enum_container, name.lower())
    raise AttributeError(f"Enum value {name!r} not found in {enum_container!r}")


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None
