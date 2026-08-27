from __future__ import annotations

import threading
import traceback
from pathlib import Path

try:
    from PySide6.QtCore import QObject, Signal, Slot
except Exception:  # pragma: no cover - optional GUI dependency
    QObject = object

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs):
            pass

        def emit(self, *args, **kwargs):
            pass

    def Slot(*args, **kwargs):  # type: ignore[no-redef]
        def deco(func):
            return func

        return deco

from resistivity372.core.config import load_yaml_file
from resistivity372.core.safety import safety_from_config
from resistivity372.measurement.sequence import load_sequence
from resistivity372.measurement.sequence_runner import validate_sequence_against_safety
from resistivity372.runtime import RuntimeFactory


class MeasurementWorker(QObject):
    """Own instrument access, acquisition, and file writes in one worker thread.

    Pause and abort only set ``threading.Event`` objects, so those two methods may be
    called directly while the worker thread is occupied by a sequence. Driver calls
    cannot be interrupted; cooperative abort takes effect after a blocking call returns.
    """

    statusChanged = Signal(dict)
    connectionStateChanged = Signal(dict)
    recordReady = Signal(object)
    stepChanged = Signal(int, str)
    logMessage = Signal(str)
    errorMessage = Signal(str)
    validationResult = Signal(bool, str)
    runStarted = Signal()
    runOutcome = Signal(str)
    finished = Signal()
    shutdownComplete = Signal()

    def __init__(self, factory: RuntimeFactory | None = None):
        super().__init__()
        self.factory = factory or RuntimeFactory()
        self.abort_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.bundle = None
        self.preview_controllers = None
        self.running = False

    @Slot(str, str)
    def validate_sequence(self, config_path: str, sequence_path: str | None = None) -> None:
        # Backward compatibility: validate_sequence(sequence_path).
        if sequence_path is None:
            sequence_path = config_path
            config_path = ""
        try:
            sequence = load_sequence(sequence_path)
            if config_path:
                config = load_yaml_file(config_path)
                validate_sequence_against_safety(sequence, safety_from_config(config))
            message = f"Validated sequence version {sequence.get('version')}: {sequence_path}"
            self.logMessage.emit(message)
            self.validationResult.emit(True, message)
        except Exception as exc:
            message = f"Sequence validation failed: {exc}"
            self.errorMessage.emit(message)
            self.validationResult.emit(False, message)

    @Slot(dict, object)
    def connect_instruments(self, config: dict, channel: object = 1) -> None:
        if self.running:
            self.errorMessage.emit("Cannot change instrument connections while a run is active.")
            return
        self._disconnect_preview()
        self.connectionStateChanged.emit({"lakeshore": "CONNECTING", "ppms": "CONNECTING"})
        self.logMessage.emit("Connecting configured instruments for status checkout...")
        controllers = None
        try:
            controllers = self.factory.create_controllers(config)
            controllers.lakeshore.connect()
            self.connectionStateChanged.emit({"lakeshore": "CONNECTED", "ppms": "CONNECTING"})
            controllers.ppms.connect()
            self.preview_controllers = controllers
            self.connectionStateChanged.emit({"lakeshore": "CONNECTED", "ppms": "CONNECTED"})
            self.logMessage.emit("Instrument connection checkout succeeded.")
            self.poll_status(channel)
        except Exception as exc:
            if controllers is not None:
                controllers.lakeshore.disconnect()
                controllers.ppms.disconnect()
            self.connectionStateChanged.emit({"lakeshore": "ERROR", "ppms": "ERROR"})
            self.errorMessage.emit(f"Instrument connection failed: {exc}")
            self.logMessage.emit(traceback.format_exc())

    @Slot()
    def disconnect_instruments(self) -> None:
        if self.running:
            self.errorMessage.emit("Use Abort Measurement before disconnecting an active run.")
            return
        self._disconnect_preview()
        self.connectionStateChanged.emit({"lakeshore": "DISCONNECTED", "ppms": "DISCONNECTED"})
        self.logMessage.emit("Instruments disconnected.")

    @Slot(object)
    def poll_status(self, channel: object = 1) -> None:
        if self.running or self.preview_controllers is None:
            return
        status: dict = {"connections": {"lakeshore": "CONNECTED", "ppms": "CONNECTED"}}
        try:
            status["ppms"] = self.preview_controllers.ppms.read_status()
        except Exception as exc:
            status["ppms_error"] = str(exc)
        try:
            status["lakeshore"] = self.preview_controllers.lakeshore.read_channel(channel)
        except Exception as exc:
            status["lakeshore_error"] = str(exc)
        self.statusChanged.emit(status)

    @Slot(str, str, str, dict)
    def start_sequence(
        self,
        config_path: str,
        sequence_path: str,
        output_path: str,
        run_metadata: dict,
    ) -> None:
        try:
            config = load_yaml_file(config_path)
        except Exception as exc:
            self.errorMessage.emit(str(exc))
            self.logMessage.emit(traceback.format_exc())
            self.runOutcome.emit("error")
            self.finished.emit()
            return
        self.start_run(config, sequence_path, output_path, run_metadata, False)

    @Slot(dict, str, str, dict, bool)
    def start_run(
        self,
        config: dict,
        sequence_path: str,
        output_path: str,
        run_metadata: dict,
        allow_overwrite: bool = False,
    ) -> None:
        if self.running:
            self.errorMessage.emit("A measurement sequence is already running.")
            return
        self.running = True
        self.abort_flag.clear()
        self.pause_flag.clear()
        self.bundle = None
        self._disconnect_preview()
        self.connectionStateChanged.emit({"lakeshore": "CONNECTING", "ppms": "CONNECTING"})
        self.runStarted.emit()
        outcome = "error"
        try:
            sequence = load_sequence(sequence_path)
            validate_sequence_against_safety(sequence, safety_from_config(config))
            self.logMessage.emit("Sequence safety validation passed; connecting instruments.")
            self.bundle = self.factory.create_bundle(
                config=config,
                sequence_path=sequence_path,
                output_path=Path(output_path),
                run_metadata=run_metadata,
                allow_overwrite=allow_overwrite,
                abort_flag=self.abort_flag,
                pause_flag=self.pause_flag,
                on_record=self._record_ready,
                on_step=self.stepChanged.emit,
                on_log=self.logMessage.emit,
            )
            self.connectionStateChanged.emit({"lakeshore": "CONNECTED", "ppms": "CONNECTED"})
            self.logMessage.emit(f"Run initialized: {output_path}")
            self.logMessage.emit("Sequence started.")
            self.bundle.runner.run(sequence)
            if self.abort_flag.is_set():
                outcome = "aborted"
                self.logMessage.emit(
                    "Measurement aborted cooperatively. No automatic PPMS safe-state commands were sent."
                )
            else:
                outcome = "completed"
                self.logMessage.emit("Sequence finished.")
        except Exception as exc:
            self.errorMessage.emit(str(exc))
            self.logMessage.emit(traceback.format_exc())
        finally:
            self._cleanup_bundle()
            self.connectionStateChanged.emit(
                {"lakeshore": "DISCONNECTED", "ppms": "DISCONNECTED"}
            )
            self.running = False
            self.runOutcome.emit(outcome)
            self.finished.emit()

    def pause(self) -> None:
        if not self.running:
            return
        self.pause_flag.set()
        self.logMessage.emit("Pause requested; it takes effect at a cooperative checkpoint.")

    def resume(self) -> None:
        if not self.running:
            return
        self.pause_flag.clear()
        self.logMessage.emit("Resume requested.")

    def abort(self) -> None:
        if not self.running:
            return
        self.abort_flag.set()
        self.pause_flag.clear()
        self.logMessage.emit(
            "Abort requested; waiting for the current blocking instrument call, if any, to return."
        )

    @Slot()
    def shutdown(self) -> None:
        if self.running:
            self.abort()
            return
        self._disconnect_preview()
        self.shutdownComplete.emit()

    def _record_ready(self, record) -> None:
        self.recordReady.emit(record)
        self.logMessage.emit(
            f"Measurement acquired: step={record.sequence_step_index} "
            f"R={record.lakeshore.resistance_ohm!s} Ohm "
            f"rho={record.resistivity_ohm_m!s} Ohm m"
        )
        self.statusChanged.emit(
            {
                "ppms": record.ppms,
                "lakeshore": record.lakeshore,
                "record": record,
                "connections": {"lakeshore": "CONNECTED", "ppms": "CONNECTED"},
            }
        )

    def _cleanup_bundle(self) -> None:
        bundle = self.bundle
        if bundle is None:
            return
        try:
            bundle.datafile.close()
        except Exception:
            self.logMessage.emit("Data-file close failed:\n" + traceback.format_exc())
        for name, controller in (
            ("Lake Shore 372", bundle.controllers.lakeshore),
            ("PPMS", bundle.controllers.ppms),
        ):
            try:
                controller.disconnect()
            except Exception:
                self.logMessage.emit(f"{name} disconnect failed:\n" + traceback.format_exc())
        self.bundle = None

    def _disconnect_preview(self) -> None:
        controllers = self.preview_controllers
        if controllers is None:
            return
        for controller in (controllers.lakeshore, controllers.ppms):
            try:
                controller.disconnect()
            except Exception:
                self.logMessage.emit("Instrument disconnect failed:\n" + traceback.format_exc())
        self.preview_controllers = None
