from __future__ import annotations

import sys
from pathlib import Path


def run_gui(args=None) -> int:
    try:
        from PySide6.QtWidgets import (
            QApplication,
            QFileDialog,
            QFormLayout,
            QHBoxLayout,
            QLabel,
            QLineEdit,
            QMainWindow,
            QPushButton,
            QTextEdit,
            QVBoxLayout,
            QWidget,
        )
    except Exception as exc:  # pragma: no cover - optional GUI dependency
        print("PySide6 is required for the GUI. Install with: pip install -e .[gui]", file=sys.stderr)
        print(str(exc), file=sys.stderr)
        return 2

    class MainWindow(QMainWindow):
        def __init__(self):
            super().__init__()
            self.setWindowTitle("LS372 + PPMS Resistivity Backbone")
            self.config_edit = QLineEdit(getattr(args, "config", "configs/example_config.yaml"))
            self.sequence_edit = QLineEdit(getattr(args, "sequence", "sequences/field_sweep_10K.yaml") or "sequences/field_sweep_10K.yaml")
            self.output_edit = QLineEdit("run_gui_placeholder.dat")
            self.log = QTextEdit()
            self.log.setReadOnly(True)

            browse_config = QPushButton("Browse config")
            browse_config.clicked.connect(lambda: self._browse(self.config_edit, "YAML files (*.yaml *.yml)"))
            browse_sequence = QPushButton("Browse sequence")
            browse_sequence.clicked.connect(lambda: self._browse(self.sequence_edit, "YAML files (*.yaml *.yml)"))
            browse_output = QPushButton("Choose output")
            browse_output.clicked.connect(lambda: self._save_as(self.output_edit))

            start = QPushButton("Start placeholder")
            start.clicked.connect(self._placeholder_start)
            abort = QPushButton("Abort placeholder")
            abort.clicked.connect(lambda: self._log("Abort button is wired in the worker skeleton."))

            form = QFormLayout()
            form.addRow("Config", self.config_edit)
            form.addRow("Sequence", self.sequence_edit)
            form.addRow("Output", self.output_edit)

            buttons = QHBoxLayout()
            buttons.addWidget(browse_config)
            buttons.addWidget(browse_sequence)
            buttons.addWidget(browse_output)
            buttons.addWidget(start)
            buttons.addWidget(abort)

            layout = QVBoxLayout()
            layout.addWidget(QLabel("Minimal GUI placeholder. Fill in panels under app/widgets as the next step."))
            layout.addLayout(form)
            layout.addLayout(buttons)
            layout.addWidget(self.log)

            central = QWidget()
            central.setLayout(layout)
            self.setCentralWidget(central)
            self.resize(900, 500)

        def _browse(self, target: QLineEdit, file_filter: str) -> None:
            path, _ = QFileDialog.getOpenFileName(self, "Choose file", str(Path.cwd()), file_filter)
            if path:
                target.setText(path)

        def _save_as(self, target: QLineEdit) -> None:
            path, _ = QFileDialog.getSaveFileName(self, "Choose output", str(Path.cwd()), "Data files (*.dat);;All files (*)")
            if path:
                target.setText(path)

        def _placeholder_start(self) -> None:
            self._log("This placeholder does not start the worker yet. Use the CLI or wire MeasurementWorker into a QThread.")
            self._log(f"Config: {self.config_edit.text()}")
            self._log(f"Sequence: {self.sequence_edit.text()}")
            self._log(f"Output: {self.output_edit.text()}")

        def _log(self, message: str) -> None:
            self.log.append(message)

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
