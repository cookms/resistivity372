from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from typing import Any, Protocol

from resistivity372.core.exceptions import InstrumentConnectionError, InstrumentError
from resistivity372.core.models import LakeShoreReading

log = logging.getLogger(__name__)


class LakeShore372Interface(Protocol):
    @property
    def is_connected(self) -> bool: ...
    def connect(self) -> None: ...
    def disconnect(self) -> None: ...
    def configure_channel(self, channel: int | str, settings: dict[str, Any]) -> None: ...
    def read_channel(self, channel: int | str) -> LakeShoreReading: ...
    def metadata(self) -> dict[str, Any]: ...


@dataclass(frozen=True)
class LakeShore372Config:
    mode: str = "tcp"
    ip_address: str | None = None
    tcp_port: int = 7777
    com_port: str | None = None
    serial_number: str | None = None
    baud_rate: int = 57600
    timeout_s: float = 2.0
    configure_on_connect: bool = False

    # GPIB support uses PyVISA and passes the VISA resource object into the
    # Lake Shore driver as an alternate connection. A full resource string
    # takes precedence; otherwise gpib_board/gpib_address are used to build one.
    gpib_resource: str | None = None
    gpib_board: int = 0
    gpib_address: int | None = None
    visa_library: str | None = None
    read_termination: str = "\n"
    write_termination: str = "\n"

    @classmethod
    def from_config(cls, config: dict) -> "LakeShore372Config":
        c = config.get("lakeshore372", {}).get("connection", {})
        return cls(
            mode=str(c.get("mode", "tcp")).lower(),
            ip_address=c.get("ip_address"),
            tcp_port=int(c.get("tcp_port", 7777)),
            com_port=c.get("com_port"),
            serial_number=c.get("serial_number"),
            baud_rate=int(c.get("baud_rate", 57600)),
            timeout_s=float(c.get("timeout_s", 2.0)),
            configure_on_connect=bool(config.get("lakeshore372", {}).get("configure_on_connect", False)),
            gpib_resource=c.get("gpib_resource"),
            gpib_board=int(c.get("gpib_board", 0)),
            gpib_address=_optional_int(c.get("gpib_address")),
            visa_library=c.get("visa_library"),
            read_termination=str(c.get("read_termination", "\n")),
            write_termination=str(c.get("write_termination", "\n")),
        )

    @property
    def resolved_gpib_resource(self) -> str:
        if self.gpib_resource:
            return self.gpib_resource
        if self.gpib_address is None:
            raise InstrumentConnectionError(
                "GPIB mode requires either connection.gpib_resource or "
                "connection.gpib_address in the Lake Shore configuration."
            )
        return f"GPIB{self.gpib_board}::{self.gpib_address}::INSTR"


class RealLakeShore372Controller:
    """Small wrapper around Lake Shore's official/custom Model372 Python driver."""

    def __init__(self, config: LakeShore372Config):
        self.config = config
        self._inst = None
        self._connected = False
        self._lock = threading.RLock()
        self._idn: str | None = None
        self._visa_rm = None
        self._visa_resource = None

    @property
    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        with self._lock:
            try:
                from lakeshore import Model372

                kwargs: dict[str, Any] = {
                    "baud_rate": self.config.baud_rate,
                    "timeout": self.config.timeout_s,
                }
                if self.config.mode == "tcp":
                    kwargs.update(
                        ip_address=self.config.ip_address,
                        tcp_port=self.config.tcp_port,
                    )
                elif self.config.mode == "usb":
                    kwargs.update(
                        serial_number=self.config.serial_number,
                        com_port=self.config.com_port,
                    )
                elif self.config.mode == "gpib":
                    kwargs.update(connection=self._open_gpib_connection())
                else:
                    raise InstrumentConnectionError(
                        f"Unsupported Lake Shore connection mode: {self.config.mode}"
                    )

                self._inst = Model372(**kwargs)
                self._idn = self._safe_query_idn()
                self._connected = True
                log.info("Connected to Lake Shore 372: %s", self._idn or "unknown ID")
            except Exception as exc:
                self._inst = None
                self._connected = False
                raise InstrumentConnectionError(
                    f"Could not connect to Lake Shore 372: {exc}"
                ) from exc

    def disconnect(self) -> None:
        with self._lock:
            try:
                if self._inst is not None:
                    if self.config.mode == "tcp" and hasattr(self._inst, "disconnect_tcp"):
                        self._inst.disconnect_tcp()
                    elif self.config.mode == "usb" and hasattr(self._inst, "disconnect_usb"):
                        self._inst.disconnect_usb()
                    elif self.config.mode == "gpib":
                        self._close_gpib_connection()
            except Exception:
                log.exception("Error while disconnecting Lake Shore 372.")
            finally:
                if self.config.mode == "gpib":
                    self._close_gpib_connection()
                self._inst = None
                self._connected = False

    def configure_channel(self, channel: int | str, settings: dict[str, Any]) -> None:
        """Apply a reviewed channel preset.

        The enum names in `settings` must be checked against the installed `lakeshore` package
        and the lab's wiring before enabling this from the GUI.
        """
        with self._lock:
            inst = self._require_connected()
            try:
                from lakeshore import Model372InputSetupSettings

                excitation_mode = settings["excitation_mode"]
                mode = getattr(inst.SensorExcitationMode, excitation_mode)
                if excitation_mode == "CURRENT":
                    range_enum = inst.MeasurementInputCurrentRange
                else:
                    range_enum = inst.MeasurementInputVoltageRange
                excitation_range = getattr(range_enum, settings["excitation_range"])
                auto_range = getattr(inst.AutoRangeMode, settings["auto_range"])
                units = getattr(inst.InputSensorUnits, settings.get("units", "OHMS"))
                resistance_range = getattr(
                    inst.MeasurementInputResistance,
                    settings["resistance_range"],
                )
                setup = Model372InputSetupSettings(
                    mode,
                    excitation_range,
                    auto_range,
                    bool(settings.get("current_source_shunted", False)),
                    units,
                    resistance_range,
                )
                inst.configure_input(channel, setup)
            except Exception as exc:
                raise InstrumentError(
                    f"Failed to configure Lake Shore 372 channel {channel}: {exc}"
                ) from exc

    def read_channel(self, channel: int | str) -> LakeShoreReading:
        with self._lock:
            inst = self._require_connected()
            try:
                if hasattr(inst, "get_all_input_readings"):
                    values = inst.get_all_input_readings(channel)
                    return LakeShoreReading(
                        channel=channel,
                        resistance_ohm=_safe_float(values.get("resistance")),
                        temperature_K=_safe_float(values.get("kelvin")),
                        excitation_power_W=_safe_float(values.get("power")),
                        quadrature_ohm=_safe_float(values.get("quadrature")),
                        raw=dict(values),
                        status="OK",
                    )

                resistance = inst.get_resistance_reading(channel)
                temperature = None
                if hasattr(inst, "get_kelvin_reading"):
                    try:
                        temperature = inst.get_kelvin_reading(channel)
                    except Exception:
                        temperature = None
                return LakeShoreReading(
                    channel=channel,
                    resistance_ohm=_safe_float(resistance),
                    temperature_K=_safe_float(temperature),
                    raw={},
                    status="OK",
                )
            except Exception as exc:
                raise InstrumentError(
                    f"Lake Shore 372 read failed on channel {channel}: {exc}"
                ) from exc

    def metadata(self) -> dict[str, Any]:
        with self._lock:
            meta = {
                "driver": "lakeshore",
                "model": "372",
                "connection_mode": self.config.mode,
                "gpib_resource": self.config.resolved_gpib_resource if self.config.mode == "gpib" else None,
                "idn": self._idn,
            }
            if self._inst is not None and hasattr(self._inst, "get_scanner_status"):
                try:
                    meta["scanner_status"] = self._inst.get_scanner_status()
                except Exception:
                    meta["scanner_status"] = "unavailable"
            return meta


    def _open_gpib_connection(self):
        """Create a PyVISA GPIB connection for the Lake Shore driver.

        Lake Shore's Python driver supports alternate connection objects via the
        ``connection=...`` constructor keyword. The object must provide
        ``write()``, ``query()``, and ``clear()`` methods, which PyVISA message
        resources do.
        """
        try:
            import pyvisa
        except Exception as exc:
            raise InstrumentConnectionError(
                "GPIB mode requires pyvisa. Install the lab hardware dependencies "
                "or run: python -m pip install pyvisa"
            ) from exc

        try:
            resource_name = self.config.resolved_gpib_resource
            self._visa_rm = pyvisa.ResourceManager(self.config.visa_library) if self.config.visa_library else pyvisa.ResourceManager()
            self._visa_resource = self._visa_rm.open_resource(resource_name)
            self._visa_resource.timeout = int(self.config.timeout_s * 1000)
            if self.config.read_termination is not None:
                self._visa_resource.read_termination = self.config.read_termination
            if self.config.write_termination is not None:
                self._visa_resource.write_termination = self.config.write_termination
            log.info("Opened Lake Shore 372 GPIB resource: %s", resource_name)
            return self._visa_resource
        except Exception as exc:
            self._close_gpib_connection()
            raise InstrumentConnectionError(f"Could not open Lake Shore GPIB resource: {exc}") from exc

    def _close_gpib_connection(self) -> None:
        for obj in (self._visa_resource, self._visa_rm):
            if obj is None:
                continue
            try:
                close = getattr(obj, "close", None)
                if callable(close):
                    close()
            except Exception:
                log.exception("Error while closing Lake Shore GPIB/VISA resource.")
        self._visa_resource = None
        self._visa_rm = None

    def _safe_query_idn(self) -> str | None:
        if self._inst is None:
            return None
        try:
            if hasattr(self._inst, "query"):
                return str(self._inst.query("*IDN?"))
        except Exception:
            return None
        return None

    def _require_connected(self):
        if not self._connected or self._inst is None:
            raise InstrumentConnectionError("Lake Shore 372 is not connected.")
        return self._inst


def _optional_int(value: object) -> int | None:
    if value is None or value == "":
        return None
    return int(value)


def _safe_float(value: object) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None
