from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone

from resistivity372.core.exceptions import InstrumentTimeoutError
from resistivity372.core.geometry import SampleGeometry
from resistivity372.core.models import LakeShoreReading, MeasurementRecord, PPMSStatus
from resistivity372.instruments.lakeshore372 import LakeShore372Interface
from resistivity372.instruments.ppms_multipyvu import PPMSInterface
from resistivity372.measurement.datafile_manager import DataFileWriter

log = logging.getLogger(__name__)


class ResistivityMeasurementEngine:
    def __init__(
        self,
        lakeshore: LakeShore372Interface,
        ppms: PPMSInterface,
        datafile: DataFileWriter,
        geometry: SampleGeometry,
        abort_flag: threading.Event,
        pause_flag: threading.Event,
        on_record=None,
        on_log=None,
        max_consecutive_read_errors: int = 10,
    ):
        self.lakeshore = lakeshore
        self.ppms = ppms
        self.datafile = datafile
        self.geometry = geometry
        self.abort_flag = abort_flag
        self.pause_flag = pause_flag
        self.on_record = on_record or (lambda record: None)
        self.on_log = on_log or (lambda msg: None)
        self.max_consecutive_read_errors = max_consecutive_read_errors
        self._consecutive_read_errors = 0

    def measure(
        self,
        channel: int | str,
        interval_s: float,
        points: int | None = None,
        duration_s: float | None = None,
        step_index: int | None = None,
        step_name: str = "",
        start_time: float | None = None,
    ) -> int:
        if points is None and duration_s is None:
            raise ValueError("Measurement step requires points or duration_s.")
        if interval_s <= 0:
            raise ValueError("Measurement interval must be positive.")

        self.geometry.validate()
        t0 = start_time if start_time is not None else time.monotonic()
        step_start = time.monotonic()
        count = 0

        while not self.abort_flag.is_set():
            self._pause_if_requested()
            if self.abort_flag.is_set():
                break
            if points is not None and count >= int(points):
                break
            if duration_s is not None and time.monotonic() - step_start >= float(duration_s):
                break

            loop_start = time.monotonic()
            record = self._read_one(channel, t0, step_index, step_name)
            self._publish_record(record)
            count += 1

            sleep_s = float(interval_s) - (time.monotonic() - loop_start)
            if sleep_s > 0:
                self._sleep_abortable(sleep_s)

        return count

    def measure_until(
        self,
        channel: int | str,
        interval_s: float,
        quantity: str,
        target: float,
        tolerance: float,
        timeout_s: float,
        require_stable: bool = False,
        settle_s: float = 0.0,
        step_index: int | None = None,
        step_name: str = "",
        start_time: float | None = None,
    ) -> int:
        """Acquire until measured PPMS state reaches and remains at a target.

        The record satisfying the stop condition is written before this method returns.
        Timeout accounting pauses while the user-requested pause flag is active.
        """
        if quantity not in {"temperature", "field"}:
            raise ValueError("measure_until quantity must be 'temperature' or 'field'.")
        if interval_s <= 0:
            raise ValueError("Measurement interval must be positive.")
        if tolerance <= 0:
            raise ValueError("Target tolerance must be positive.")
        if timeout_s <= 0:
            raise ValueError("Measurement timeout must be positive.")
        if settle_s < 0:
            raise ValueError("Target settle time cannot be negative.")

        self.geometry.validate()
        t0 = start_time if start_time is not None else time.monotonic()
        deadline = time.monotonic() + float(timeout_s)
        stable_since: float | None = None
        count = 0

        while not self.abort_flag.is_set():
            deadline += self._pause_if_requested()
            if self.abort_flag.is_set():
                break
            if time.monotonic() > deadline:
                raise InstrumentTimeoutError(
                    f"Continuous acquisition did not reach stable {quantity} target "
                    f"{target:g} within {timeout_s:g} s."
                )

            loop_start = time.monotonic()
            record = self._read_one(channel, t0, step_index, step_name)
            self._publish_record(record)
            count += 1

            value, _status = _condition_value(record.ppms, quantity)
            at_target = value is not None and abs(value - float(target)) <= float(tolerance)
            now = time.monotonic()
            if at_target:
                if stable_since is None:
                    stable_since = now
                if now - stable_since >= settle_s:
                    return count
            else:
                stable_since = None

            sleep_s = min(float(interval_s), max(0.0, deadline - time.monotonic()))
            sleep_s -= time.monotonic() - loop_start
            if sleep_s > 0:
                self._sleep_abortable(sleep_s)

        return count

    def _read_one(
        self,
        channel: int | str,
        t0: float,
        step_index: int | None,
        step_name: str,
    ) -> MeasurementRecord:
        timestamp = datetime.now(timezone.utc)
        elapsed = time.monotonic() - t0
        error_parts: list[str] = []

        try:
            ppms_status = self.ppms.read_status()
        except Exception as exc:
            ppms_status = PPMSStatus(
                temperature_K=None,
                temperature_status="ERROR",
                field_T=None,
                field_status="ERROR",
                chamber_status="ERROR",
            )
            error_parts.append(f"PPMS_READ_ERROR: {exc}")

        try:
            ls_reading = self.lakeshore.read_channel(channel)
        except Exception as exc:
            ls_reading = LakeShoreReading(
                channel=channel,
                resistance_ohm=None,
                status="ERROR",
            )
            error_parts.append(f"LS372_READ_ERROR: {exc}")

        rho_m, rho_cm = self.geometry.resistivity(ls_reading.resistance_ohm)
        return MeasurementRecord(
            timestamp_utc=timestamp,
            elapsed_s=elapsed,
            ppms=ppms_status,
            lakeshore=ls_reading,
            resistivity_ohm_m=rho_m,
            resistivity_ohm_cm=rho_cm,
            sequence_step_index=step_index,
            sequence_step_name=step_name,
            error="; ".join(error_parts),
        )

    def _publish_record(self, record: MeasurementRecord) -> None:
        self.datafile.write_record(record)
        self.on_record(record)
        if record.error:
            self._consecutive_read_errors += 1
            self.on_log(record.error)
        else:
            self._consecutive_read_errors = 0
        if self._consecutive_read_errors >= self.max_consecutive_read_errors:
            raise RuntimeError(
                f"Stopping after {self._consecutive_read_errors} consecutive read errors."
            )

    def _pause_if_requested(self) -> float:
        if not self.pause_flag.is_set():
            return 0.0
        paused_at = time.monotonic()
        while self.pause_flag.is_set() and not self.abort_flag.is_set():
            time.sleep(0.05)
        return time.monotonic() - paused_at

    def _sleep_abortable(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self.abort_flag.is_set() and time.monotonic() < deadline:
            time.sleep(min(0.05, deadline - time.monotonic()))


def _condition_value(status: PPMSStatus, quantity: str) -> tuple[float | None, object]:
    if quantity == "temperature":
        return status.temperature_K, status.temperature_status
    return status.field_T, status.field_status
