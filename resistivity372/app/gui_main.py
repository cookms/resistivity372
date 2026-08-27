from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from resistivity372.app.models import (
    ApplicationState,
    RunPreparation,
    build_effective_config,
    compose_run_metadata,
    controls_for_state,
)
from resistivity372.app.qt_worker import MeasurementWorker
from resistivity372.app.widgets import (
    ConnectionPanel,
    GeometryPanel,
    LogPanel,
    PlotPanel,
    RunSetupPanel,
    SequenceEditor,
    StatusPanel,
)
from resistivity372.core.config import deep_update, dotted_set, load_yaml_file
from resistivity372.core.logging_setup import setup_logging
from resistivity372.core.safety import safety_from_config
from resistivity372.runtime import resolve_instrument_simulation_mode


ACTIVE_STATES = {
    ApplicationState.STARTING,
    ApplicationState.RUNNING,
    ApplicationState.PAUSED,
    ApplicationState.ABORTING,
}


class MainWindow(QMainWindow):
    startRequested = Signal(dict, str, str, dict, bool)
    connectRequested = Signal(dict, object)
    disconnectRequested = Signal()
    pollRequested = Signal(object)
    shutdownRequested = Signal()

    def __init__(self, args=None, parent=None):
        super().__init__(parent)
        self.args = args
        self.base_config: dict = {}
        self.preparation = RunPreparation()
        self.state = ApplicationState.IDLE
        self.last_outcome = ""
        self._closing_pending = False
        self._force_close = False
        self._qt_log_handler = None

        self.setWindowTitle("LS372 + PPMS Resistivity Measurement")
        self.config_edit = QLineEdit(
            str(getattr(args, "config", "configs/example_config.yaml"))
        )
        browse_config = QPushButton("Choose Config")
        self.load_config_button = QPushButton("Load Config")
        browse_config.clicked.connect(self._browse_config)
        self.load_config_button.clicked.connect(self.load_config)
        config_row = QHBoxLayout()
        config_row.addWidget(QLabel("Base YAML configuration"))
        config_row.addWidget(self.config_edit, 1)
        config_row.addWidget(browse_config)
        config_row.addWidget(self.load_config_button)

        self.run_setup = RunSetupPanel()
        self.geometry_panel = GeometryPanel()
        self.connection_panel = ConnectionPanel()
        self.status_panel = StatusPanel()
        self.sequence_editor = SequenceEditor()
        self.log_panel = LogPanel()
        self.plot_panel = PlotPanel()

        left_content = QWidget()
        left_layout = QVBoxLayout(left_content)
        left_layout.addWidget(self.run_setup)
        left_layout.addWidget(self.geometry_panel)
        left_layout.addStretch(1)
        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setWidget(left_content)
        right_content = QWidget()
        right_layout = QVBoxLayout(right_content)
        right_layout.addWidget(self.connection_panel)
        right_layout.addWidget(self.status_panel)
        right_layout.addStretch(1)
        top_splitter = QSplitter(Qt.Orientation.Horizontal)
        top_splitter.addWidget(left_scroll)
        top_splitter.addWidget(right_content)
        top_splitter.setSizes([720, 560])

        sequence_group = QGroupBox("Sequence Configuration / YAML Editor")
        sequence_layout = QVBoxLayout(sequence_group)
        sequence_layout.addWidget(self.sequence_editor)

        self.start_button = QPushButton("Start Measurement")
        self.pause_button = QPushButton("Pause")
        self.resume_button = QPushButton("Resume")
        self.abort_button = QPushButton("Abort Measurement")
        self.state_label = QLabel("IDLE")
        self.state_label.setStyleSheet("font-weight: 700;")
        self.step_label = QLabel("Current step: N/A")
        controls = QHBoxLayout()
        controls.addWidget(self.start_button)
        controls.addWidget(self.pause_button)
        controls.addWidget(self.resume_button)
        controls.addWidget(self.abort_button)
        controls.addSpacing(20)
        controls.addWidget(QLabel("Application state:"))
        controls.addWidget(self.state_label)
        controls.addSpacing(20)
        controls.addWidget(self.step_label, 1)

        self.latest_labels = {
            "resistance": QLabel("N/A"),
            "resistivity": QLabel("N/A"),
            "temperature": QLabel("N/A"),
            "field": QLabel("N/A"),
            "elapsed": QLabel("N/A"),
        }
        latest = QHBoxLayout()
        for caption, key in (
            ("Resistance", "resistance"),
            ("Resistivity", "resistivity"),
            ("PPMS T", "temperature"),
            ("Field", "field"),
            ("Elapsed", "elapsed"),
        ):
            latest.addWidget(QLabel(caption + ":"))
            latest.addWidget(self.latest_labels[key])
            latest.addSpacing(12)
        latest.addStretch(1)

        lower_tabs = QTabWidget()
        lower_tabs.addTab(self.plot_panel, "Live Plot")
        lower_tabs.addTab(self.log_panel, "Application Log")
        main_splitter = QSplitter(Qt.Orientation.Vertical)
        main_splitter.addWidget(top_splitter)
        main_splitter.addWidget(sequence_group)
        main_splitter.addWidget(lower_tabs)
        main_splitter.setSizes([430, 330, 300])

        central = QWidget()
        layout = QVBoxLayout(central)
        layout.addLayout(config_row)
        layout.addWidget(main_splitter, 1)
        layout.addLayout(controls)
        layout.addLayout(latest)
        self.setCentralWidget(central)
        self.resize(1450, 980)

        self.worker_thread = QThread(self)
        self.worker_thread.setObjectName("MeasurementWorkerThread")
        self.worker = MeasurementWorker()
        self.worker.moveToThread(self.worker_thread)
        self.startRequested.connect(self.worker.start_run)
        self.connectRequested.connect(self.worker.connect_instruments)
        self.disconnectRequested.connect(self.worker.disconnect_instruments)
        self.pollRequested.connect(self.worker.poll_status)
        self.shutdownRequested.connect(self.worker.shutdown)
        self.worker.recordReady.connect(self._on_record)
        self.worker.statusChanged.connect(self.status_panel.update_status)
        self.worker.connectionStateChanged.connect(self.connection_panel.set_connection_state)
        self.worker.logMessage.connect(self.log_panel.append_message)
        self.worker.errorMessage.connect(self._on_error)
        self.worker.runStarted.connect(self._on_run_started)
        self.worker.runOutcome.connect(self._on_outcome)
        self.worker.stepChanged.connect(self._on_step)
        self.worker.finished.connect(self._on_finished)
        self.worker.shutdownComplete.connect(self._on_shutdown_complete)
        self.worker_thread.finished.connect(self.worker.deleteLater)
        self.worker_thread.start()

        self.connection_panel.connectRequested.connect(self._connect_instruments)
        self.connection_panel.disconnectRequested.connect(self.disconnectRequested)
        self.run_setup.initializeRequested.connect(self._initialize_run)
        self.run_setup.changed.connect(self._invalidate_run)
        self.geometry_panel.geometryChanged.connect(self._invalidate_run)
        self.sequence_editor.contentChanged.connect(self._sequence_changed)
        self.sequence_editor.validationChanged.connect(self._sequence_validation_changed)
        self.sequence_editor.validate_button.clicked.connect(self._validate_sequence)
        self.start_button.clicked.connect(self._start)
        self.pause_button.clicked.connect(self._pause)
        self.resume_button.clicked.connect(self._resume)
        self.abort_button.clicked.connect(self._abort)

        self.poll_timer = QTimer(self)
        self.poll_timer.timeout.connect(self._poll_idle_status)
        self._set_state(ApplicationState.IDLE)
        self.load_config()
        sequence_arg = getattr(args, "sequence", None)
        default_sequence = sequence_arg or "sequences/smoke_simulation.yaml"
        if Path(default_sequence).exists():
            self.sequence_editor.set_path(default_sequence)
        output_arg = getattr(args, "output", None)
        if output_arg:
            output = Path(output_arg)
            self.run_setup.output_dir.setText(str(output.parent))
            self.run_setup.filename.setText(output.name)

    def load_config(self) -> None:
        try:
            config = load_yaml_file(self.config_edit.text().strip())
            if getattr(self.args, "simulate", False):
                dotted_set(config, "mode.simulation", True)
            if getattr(self.args, "dry_run", False):
                dotted_set(config, "mode.dry_run", True)
            self.base_config = config
            self.preparation.config_path = Path(self.config_edit.text().strip())
            self.run_setup.set_config(config)
            self.geometry_panel.set_config(config)
            self.connection_panel.set_config(config)
            self._configure_logging(config)
            refresh = int(config.get("gui", {}).get("refresh_interval_ms", 1000))
            self.poll_timer.start(max(500, refresh))
            self._invalidate_run()
            self._set_state(ApplicationState.CONFIGURING)
            self.log_panel.append_message(f"Configuration loaded: {self.preparation.config_path}")
        except Exception as exc:
            self.base_config = {}
            self._set_state(ApplicationState.ERROR)
            self._on_error(f"Configuration load failed: {exc}")

    def effective_config(self) -> dict:
        config = build_effective_config(
            self.base_config,
            self.run_setup.sample_metadata(),
            self.run_setup.run_metadata(),
            self.geometry_panel.geometry_config(),
        )
        return deep_update(config, {"data": {"backend": self.run_setup.backend.currentText()}})

    def _validate_sequence(self) -> None:
        if not self.base_config:
            self._on_error("Load a valid configuration before validating a sequence.")
            return
        try:
            safety = safety_from_config(self.effective_config())
            valid, message = self.sequence_editor.validate_current(safety)
        except Exception as exc:
            valid, message = False, f"Sequence validation failed: {exc}"
        self.preparation.sequence_valid = valid and self.sequence_editor.ready_for_run
        self.preparation.sequence_path = self.sequence_editor.path
        self.preparation.summary = self.sequence_editor.summary
        self.preparation.validation_fingerprint = self.sequence_editor.validation_fingerprint
        self.log_panel.append_message(message, "INFO" if valid else "ERROR")
        self._invalidate_run()

    def _initialize_run(self) -> None:
        if not self.base_config:
            self._on_error("Load a valid configuration first.")
            return
        geometry_state, geometry_message = self.geometry_panel.validation_state()
        if geometry_state == "invalid":
            self._on_error("Cannot initialize run: " + geometry_message)
            return
        if not self.sequence_editor.ready_for_run:
            self._on_error("Validate and save the current sequence before initializing the run.")
            return
        path = self.run_setup.output_path
        if path is None or not path.name:
            self._on_error("Choose an output directory and run filename.")
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            self._on_error(f"Could not prepare output directory: {exc}")
            return
        allow_overwrite = bool(getattr(self.args, "allow_overwrite", False))
        if path.exists() and not allow_overwrite:
            answer = QMessageBox.warning(
                self,
                "Existing data file",
                f"The destination already exists:\n{path}\n\nExplicitly allow overwrite for this run?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                self.run_setup.set_initialized(False, "Run not initialized - existing file retained")
                return
            allow_overwrite = True
        self.preparation.output_path = path
        self.preparation.sequence_path = self.sequence_editor.path
        self.preparation.sequence_valid = True
        self.preparation.allow_overwrite = allow_overwrite
        self.preparation.run_initialized = True
        self.preparation.errors.clear()
        geometry_note = (
            "resistivity enabled" if geometry_state == "valid" else "resistance only"
        )
        self.run_setup.set_initialized(
            True,
            f"Run ready: {path} ({self.run_setup.backend.currentText()}, {geometry_note})",
        )
        self._set_state(ApplicationState.READY)
        self.log_panel.append_message(
            f"Run initialized for {path}; backend={self.run_setup.backend.currentText()}; {geometry_note}."
        )

    def _start(self) -> None:
        if self.state is not ApplicationState.READY or not self.preparation.ready:
            self._on_error("Run is not ready. Validate the sequence and initialize the run.")
            return
        if not self.sequence_editor.ready_for_run:
            self._on_error("The sequence changed after validation; validate and initialize again.")
            self._invalidate_run()
            return
        output = self.preparation.output_path
        if output is None:
            return
        if output.exists() and not self.preparation.allow_overwrite:
            self._on_error("The output file now exists; initialize the run again to confirm overwrite.")
            self._invalidate_run()
            return
        try:
            config = self.effective_config()
        except Exception as exc:
            self._on_error(f"Effective run configuration is invalid: {exc}")
            return
        if not self._confirm_real_hardware(config):
            return
        simulation = resolve_instrument_simulation_mode(config)
        run_metadata = compose_run_metadata(
            self.run_setup.sample_metadata(),
            self.run_setup.run_metadata(),
            self.geometry_panel.geometry_config(),
            output,
            self.run_setup.backend.currentText(),
            {
                "global": simulation.global_simulation,
                "lakeshore": simulation.lakeshore,
                "ppms": simulation.ppms,
            },
            bool(config.get("mode", {}).get("dry_run", False)),
        )
        self.plot_panel.clear()
        self._set_state(ApplicationState.STARTING)
        self._set_run_fields_locked(True)
        self.log_panel.append_message(f"Starting sequence: {self.preparation.sequence_path}")
        self.startRequested.emit(
            config,
            str(self.preparation.sequence_path),
            str(output),
            run_metadata,
            self.preparation.allow_overwrite,
        )

    def _pause(self) -> None:
        if self.state is ApplicationState.RUNNING:
            self.worker.pause()
            self._set_state(ApplicationState.PAUSED)

    def _resume(self) -> None:
        if self.state is ApplicationState.PAUSED:
            self.worker.resume()
            self._set_state(ApplicationState.RUNNING)

    def _abort(self) -> None:
        if self.state in {ApplicationState.RUNNING, ApplicationState.PAUSED}:
            self.worker.abort()
            self._set_state(ApplicationState.ABORTING)

    def _connect_instruments(self) -> None:
        if self.state in ACTIVE_STATES:
            return
        try:
            config = self.effective_config()
            channel = config.get("lakeshore372", {}).get("default_channel", 1)
            self.connectRequested.emit(config, channel)
        except Exception as exc:
            self._on_error(f"Cannot connect: {exc}")

    def _poll_idle_status(self) -> None:
        if self.state not in ACTIVE_STATES and self.base_config:
            channel = self.base_config.get("lakeshore372", {}).get("default_channel", 1)
            self.pollRequested.emit(channel)

    def _on_record(self, record) -> None:
        self.plot_panel.add_record(record)
        self.latest_labels["resistance"].setText(_number(record.lakeshore.resistance_ohm, " Ohm"))
        self.latest_labels["resistivity"].setText(_number(record.resistivity_ohm_m, " Ohm m"))
        self.latest_labels["temperature"].setText(_number(record.ppms.temperature_K, " K"))
        self.latest_labels["field"].setText(_number(record.ppms.field_T, " T"))
        self.latest_labels["elapsed"].setText(_number(record.elapsed_s, " s"))

    def _on_run_started(self) -> None:
        self._set_state(ApplicationState.RUNNING)
        if self._closing_pending:
            self._abort()

    def _on_step(self, index: int, name: str) -> None:
        self.step_label.setText(f"Current step {index}: {name}")

    def _on_error(self, message: str) -> None:
        self.log_panel.append_error(message)
        if self.state in ACTIVE_STATES:
            self._set_state(ApplicationState.ERROR)

    def _on_outcome(self, outcome: str) -> None:
        self.last_outcome = outcome
        if outcome == "error":
            self._set_state(ApplicationState.ERROR)
        else:
            self._set_state(ApplicationState.COMPLETED)
            self.state_label.setText("ABORTED" if outcome == "aborted" else "COMPLETED")

    def _on_finished(self) -> None:
        self._set_run_fields_locked(False)
        self.preparation.invalidate_run()
        self.run_setup.set_initialized(False, "Run ended; initialize a new destination before starting again")
        self._update_controls()
        if self._closing_pending:
            self.shutdownRequested.emit()

    def _sequence_changed(self) -> None:
        self.preparation.sequence_path = self.sequence_editor.path
        self.preparation.sequence_valid = self.sequence_editor.ready_for_run
        self._invalidate_run()

    def _sequence_validation_changed(self, valid: bool, _message: str) -> None:
        self.preparation.sequence_valid = valid and self.sequence_editor.ready_for_run
        self.preparation.summary = self.sequence_editor.summary
        self._update_controls()

    def _invalidate_run(self) -> None:
        if self.state in ACTIVE_STATES:
            return
        self.preparation.invalidate_run()
        self.run_setup.set_initialized(False, "Run not initialized")
        if self.base_config:
            self._set_state(ApplicationState.CONFIGURING)
        else:
            self._set_state(ApplicationState.IDLE)

    def _set_state(self, state: ApplicationState) -> None:
        self.state = state
        self.state_label.setText(state.value)
        self._update_controls()

    def _update_controls(self) -> None:
        controls = controls_for_state(self.state, self.preparation.ready)
        self.start_button.setEnabled(controls.start)
        self.pause_button.setEnabled(controls.pause)
        self.resume_button.setEnabled(controls.resume)
        self.abort_button.setEnabled(controls.abort)
        self.connection_panel.set_controls_enabled(controls.configure)

    def _set_run_fields_locked(self, locked: bool) -> None:
        self.run_setup.set_locked(locked)
        self.geometry_panel.set_locked(locked)
        self.sequence_editor.set_locked(locked)
        self.config_edit.setReadOnly(locked)
        self.load_config_button.setEnabled(not locked)

    def _confirm_real_hardware(self, config: dict) -> bool:
        simulation = resolve_instrument_simulation_mode(config)
        dry_run = bool(config.get("mode", {}).get("dry_run", False))
        if simulation.ppms or dry_run:
            return True
        summary = self.preparation.summary
        temp = summary.temperature_extrema if summary else None
        field = summary.field_extrema if summary else None
        details = [
            "REAL PPMS control is enabled.",
            f"LS372: {'SIMULATED' if simulation.lakeshore else 'REAL'}",
            "DRY RUN: OFF",
            f"Sequence: {self.preparation.sequence_path}",
            f"Output: {self.preparation.output_path}",
            f"Temperature extrema: {temp if temp else 'no targets'} K",
            f"Field extrema: {field if field else 'no targets'} T",
            "",
            "This confirmation does not add any hardware safety action.",
        ]
        answer = QMessageBox.warning(
            self,
            "Confirm real PPMS control",
            "\n".join(details),
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _browse_config(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Choose configuration", str(Path.cwd()), "YAML files (*.yaml *.yml)"
        )
        if selected:
            self.config_edit.setText(selected)
            self.load_config()

    def _configure_logging(self, config: dict) -> None:
        path = setup_logging(config)
        self._qt_log_handler = self.log_panel.make_logging_handler()
        logging.getLogger().addHandler(self._qt_log_handler)
        self.log_panel.append_message(f"Application log: {path}")

    def closeEvent(self, event) -> None:
        if self._force_close:
            event.accept()
            return
        if self.state in ACTIVE_STATES:
            answer = QMessageBox.warning(
                self,
                "Measurement active",
                "A measurement is active. Request cooperative abort and close after cleanup?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self._closing_pending = True
            self._abort()
            event.ignore()
            return
        self._closing_pending = True
        self.shutdownRequested.emit()
        event.ignore()

    def _on_shutdown_complete(self) -> None:
        self.poll_timer.stop()
        self.worker_thread.quit()
        self.worker_thread.wait(5000)
        if self._qt_log_handler is not None:
            logging.getLogger().removeHandler(self._qt_log_handler)
        self._force_close = True
        QTimer.singleShot(0, self.close)


def run_gui(args=None) -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    window = MainWindow(args=args)
    window.show()
    return app.exec()


def _number(value, suffix: str) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.7g}{suffix}"
    except (TypeError, ValueError):
        return "N/A"
