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
    def set_temperature(
        self, setpoint_K: float, rate_K_per_min: float, approach: str = "fast_settle"
    ) -> None: ...
    def set_field(
        self,
        setpoint_T: float,
        rate_T_per_min: float,
        approach: str = "linear",
        driven_mode: str | None = None,
    ) -> None: ...
    def set_chamber(self, mode_name: str) -> None: ...
    def set_position(self, position_deg: float, rate_deg_per_s: float) -> None: ...
    def wait_for_temperature(
        self,
        target_K: float,
        tolerance_K: float,
        stable_s: float,
        equilibration_s: float,
        timeout_s: float,
        abort_flag,
        poll_s: float = 2.0,
    ) -> None: ...
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
    ) -> None: ...
    def wait_for_chamber(
        self,
        target_mode: str,
        stable_s: float,
        equilibration_s: float,
        timeout_s: float,
        abort_flag,
        poll_s: float = 2.0,
    ) -> None: ...


@dataclass(frozen=True)
class PPMSConfig:
    host: str = "127.0.0.1"
    port: int = 5000
    socket_timeout_s: float | None = 10.0
    platform: str = "ppms"
    use_position: bool = False
    field_read_delay_s: float = 10.0
    default_field_driven_mode: str | None = "auto"

    @classmethod
    def from_config(cls, config: dict) -> "PPMSConfig":
        c = config.get("ppms", {})
        return cls(
            host=c.get("host", "127.0.0.1"),
            port=int(c.get("port", 5000)),
            socket_timeout_s=c.get("socket_timeout_s", 10.0),
            platform=c.get("platform", "ppms"),
            use_position=bool(c.get("use_position", False)),
            field_read_delay_s=max(0.0, float(c.get("field_read_delay_s", 10.0))),
            default_field_driven_mode=_optional_name(c.get("default_field_driven_mode", "auto")),
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
        self._field_read_safe_after = 0.0
        self._last_field_command_at = 0.0

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
                log.info(
                    "Connected to MultiPyVu server at %s:%s", self.config.host, self.config.port
                )
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
                if time.monotonic() >= self._field_read_safe_after:
                    field_oe, field_status = c.get_field()
                else:
                    field_oe = None
                    field_status = "unavailable_after_set_field"
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

    def set_temperature(
        self, setpoint_K: float, rate_K_per_min: float, approach: str = "fast_settle"
    ) -> None:
        self.safety.check_temperature(setpoint_K, rate_K_per_min)
        if self.dry_run:
            log.info(
                "DRY-RUN: set_temperature(%s K, %s K/min, %s)", setpoint_K, rate_K_per_min, approach
            )
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
        selected_driven_mode = self._field_driven_mode(driven_mode)
        if self.dry_run:
            log.info(
                "DRY-RUN: set_field(%s T, %s T/min, approach=%s, driven_mode=%s)",
                setpoint_T,
                rate_T_per_min,
                approach,
                selected_driven_mode,
            )
            return
        with self._lock:
            c = self._require_connected()
            try:
                approach_mode = _resolve_enum(c.field.approach_mode, approach)
                if selected_driven_mode:
                    driven = _resolve_enum(c.field.driven_mode, selected_driven_mode)
                    c.set_field(setpoint_oe, rate_oe_per_s, approach_mode, driven)
                else:
                    c.set_field(setpoint_oe, rate_oe_per_s, approach_mode)
                self._last_field_command_at = time.monotonic()
                self._field_read_safe_after = (
                    self._last_field_command_at + self.config.field_read_delay_s
                )
            except Exception as exc:
                raise InstrumentError(f"PPMS set_field failed: {exc}") from exc

    def _field_driven_mode(self, requested_mode: str | None) -> str | None:
        if requested_mode:
            return requested_mode
        configured = self.config.default_field_driven_mode
        if configured != "auto":
            return configured
        platform = self.config.platform.strip().lower().replace("-", "_").replace(" ", "_")
        if platform in {"ppms", "ppms_6000", "ppms6000", "model_6000"}:
            return "persistent"
        return None

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
        if self.dry_run:
            log.info("DRY-RUN: wait_for_temperature(%s K)", target_K)
            return

        def temperature_is_stable() -> bool:
            with self._lock:
                value, _status = self._require_connected().get_temperature()
            measured = _safe_float(value)
            return measured is not None and abs(measured - target_K) <= tolerance_K

        self._wait_for_condition(
            condition=temperature_is_stable,
            description=f"temperature {target_K:g} +/- {tolerance_K:g} K",
            stable_s=stable_s,
            equilibration_s=equilibration_s,
            timeout_s=timeout_s,
            abort_flag=abort_flag,
            poll_s=poll_s,
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
        if self.dry_run:
            log.info("DRY-RUN: wait_for_field(%s T)", target_T)
            return
        wait_started = time.monotonic()
        if read_delay_s is not None:
            self._field_read_safe_after = max(
                self._field_read_safe_after,
                self._last_field_command_at + max(0.0, read_delay_s),
            )
        self._sleep_until_field_read_safe(abort_flag)
        remaining_timeout_s = timeout_s - (time.monotonic() - wait_started)
        if remaining_timeout_s <= 0:
            raise InstrumentTimeoutError(
                f"PPMS field could not be read within the {timeout_s:g} s timeout."
            )

        def field_is_stable() -> bool:
            with self._lock:
                value_oe, _status = self._require_connected().get_field()
            value = _safe_float(value_oe)
            measured_T = value / OE_PER_TESLA if value is not None else None
            return measured_T is not None and abs(measured_T - target_T) <= tolerance_T

        self._wait_for_condition(
            condition=field_is_stable,
            description=f"field {target_T:g} +/- {tolerance_T:g} T",
            stable_s=stable_s,
            equilibration_s=equilibration_s,
            timeout_s=remaining_timeout_s,
            abort_flag=abort_flag,
            poll_s=poll_s,
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
        if self.dry_run:
            log.info("DRY-RUN: wait_for_chamber(%s)", target_mode)
            return

        def chamber_is_stable() -> bool:
            with self._lock:
                status = self._require_connected().get_chamber()
            return _chamber_status_matches(status, target_mode)

        self._wait_for_condition(
            condition=chamber_is_stable,
            description=f"chamber mode {target_mode}",
            stable_s=stable_s,
            equilibration_s=equilibration_s,
            timeout_s=timeout_s,
            abort_flag=abort_flag,
            poll_s=poll_s,
        )

    def _wait_for_condition(
        self,
        *,
        condition,
        description: str,
        stable_s: float,
        equilibration_s: float,
        timeout_s: float,
        abort_flag,
        poll_s: float,
    ) -> None:
        deadline = time.monotonic() + timeout_s
        stable_since: float | None = None
        while True:
            self._raise_if_aborted(abort_flag)
            now = time.monotonic()
            if now > deadline:
                raise InstrumentTimeoutError(
                    f"PPMS did not hold {description} for {stable_s:g} s within {timeout_s:g} s."
                )
            if condition():
                stable_since = stable_since if stable_since is not None else now
                if now - stable_since >= stable_s:
                    break
            else:
                stable_since = None
            self._sleep_abortable(min(poll_s, max(0.0, deadline - time.monotonic())), abort_flag)

        self._sleep_abortable(equilibration_s, abort_flag)

    def _sleep_until_field_read_safe(self, abort_flag) -> None:
        while True:
            remaining = self._field_read_safe_after - time.monotonic()
            if remaining <= 0:
                return
            self._sleep_abortable(min(remaining, 0.1), abort_flag)

    @staticmethod
    def _sleep_abortable(seconds: float, abort_flag) -> None:
        deadline = time.monotonic() + max(0.0, seconds)
        while time.monotonic() < deadline:
            RealPPMSController._raise_if_aborted(abort_flag)
            time.sleep(min(0.05, deadline - time.monotonic()))

    @staticmethod
    def _raise_if_aborted(abort_flag) -> None:
        if abort_flag.is_set():
            raise InstrumentError("Wait aborted by user.")

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


def _optional_name(value: object) -> str | None:
    if value is None:
        return None
    name = str(value).strip()
    return name or None


def _normalized_status(value: object) -> str:
    name = getattr(value, "name", value)
    return str(name).strip().lower().replace("-", "_").replace(" ", "_").rsplit(".", 1)[-1]


def _chamber_status_matches(status: object, target_mode: str) -> bool:
    actual = _normalized_status(status)
    target = _normalized_status(target_mode)
    accepted = {
        "seal": {
            "seal",
            "sealed",
            "purged_and_sealed",
            "vented_and_sealed",
            "sealed_(condition_unknown)",
        },
        "purge_seal": {"purge_seal", "purged_and_sealed"},
        "vent_seal": {"vent_seal", "vented_and_sealed"},
        "pump_continuous": {"pump_continuous", "pumping_continuously"},
        "vent_continuous": {"vent_continuous", "flooding_continuously"},
        "high_vacuum": {"high_vacuum", "hivac"},
    }
    return actual in accepted.get(target, {target})
