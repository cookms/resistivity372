from __future__ import annotations

import threading
import traceback
from pathlib import Path

try:
    from PySide6.QtCore import QObject, Signal, Slot
except Exception:  # pragma: no cover - optional GUI dependency
    QObject = object

    class Signal:  # type: ignore[no-redef]
        def __init__(self, *args, **kwargs): pass
        def emit(self, *args, **kwargs): pass

    def Slot(*args, **kwargs):  # type: ignore[no-redef]
        def deco(func):
            return func
        return deco

from resistivity372.core.config import load_yaml_file
from resistivity372.measurement.sequence import load_sequence
from resistivity372.runtime import RuntimeFactory


class MeasurementWorker(QObject):
    statusChanged = Signal(dict)
    recordReady = Signal(object)
    logMessage = Signal(str)
    errorMessage = Signal(str)
    finished = Signal()

    def __init__(self, factory: RuntimeFactory | None = None):
        super().__init__()
        self.factory = factory or RuntimeFactory()
        self.abort_flag = threading.Event()
        self.pause_flag = threading.Event()
        self.bundle = None

    @Slot(str)
    def validate_sequence(self, sequence_path: str) -> None:
        try:
            seq = load_sequence(sequence_path)
            # Full safety validation occurs after config/controllers are available.
            self.logMessage.emit(f"Loaded sequence version {seq.get('version')}: {sequence_path}")
        except Exception as exc:
            self.errorMessage.emit(f"Sequence validation failed: {exc}")

    @Slot(str, str, str, dict)
    def start_sequence(self, config_path: str, sequence_path: str, output_path: str, run_metadata: dict) -> None:
        self.abort_flag.clear()
        self.pause_flag.clear()
        try:
            config = load_yaml_file(config_path)
            sequence = load_sequence(sequence_path)
            self.bundle = self.factory.create_bundle(
                config=config,
                sequence_path=sequence_path,
                output_path=Path(output_path),
                run_metadata=run_metadata,
                abort_flag=self.abort_flag,
                pause_flag=self.pause_flag,
                on_record=self.recordReady.emit,
                on_log=self.logMessage.emit,
            )
            self.bundle.runner.run(sequence)
            self.logMessage.emit("Sequence finished.")
        except Exception as exc:
            self.errorMessage.emit(f"{exc}\n{traceback.format_exc()}")
        finally:
            try:
                if self.bundle is not None:
                    self.bundle.datafile.close()
            finally:
                self.finished.emit()

    @Slot()
    def pause(self) -> None:
        self.pause_flag.set()
        self.logMessage.emit("Pause requested.")

    @Slot()
    def resume(self) -> None:
        self.pause_flag.clear()
        self.logMessage.emit("Resume requested.")

    @Slot()
    def abort(self) -> None:
        self.abort_flag.set()
        self.logMessage.emit("Abort requested.")
