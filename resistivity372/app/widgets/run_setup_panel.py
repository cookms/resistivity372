from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from resistivity372.app.models import RunMetadata, SampleMetadata, suggested_filename


class RunSetupPanel(QGroupBox):
    changed = Signal()
    initializeRequested = Signal()

    def __init__(self, parent=None):
        super().__init__("Sample and Run Setup", parent)
        self.sample_id = QLineEdit()
        self.material = QLineEdit()
        self.operator = QLineEdit()
        self.experiment_name = QLineEdit()
        self.notebook = QLineEdit()
        self.cooldown = QLineEdit()
        self.contacts = QLineEdit()
        self.orientation = QLineEdit()
        self.notes = QTextEdit()
        self.notes.setMaximumHeight(70)
        self.output_dir = QLineEdit()
        self.filename = QLineEdit()
        self.backend = QComboBox()
        self.backend.addItems(["csv", "multipyvu"])
        self.final_path = QLabel("Output path not selected")
        self.final_path.setWordWrap(True)
        self.ready_label = QLabel("Run not initialized")
        self.initialize_button = QPushButton("Initialize Run")
        self.suggest_button = QPushButton("Suggest Filename")

        sample_form = QFormLayout()
        sample_form.addRow("Sample ID / name", self.sample_id)
        sample_form.addRow("Material / formula", self.material)
        sample_form.addRow("Operator", self.operator)
        sample_form.addRow("Experiment / run name", self.experiment_name)
        sample_form.addRow("Lab notebook reference", self.notebook)
        sample_form.addRow("Cooldown / run ID", self.cooldown)
        sample_form.addRow("Contact configuration", self.contacts)
        sample_form.addRow("Current direction / orientation", self.orientation)
        sample_form.addRow("Notes", self.notes)

        choose_dir = QPushButton("Choose Directory")
        choose_file = QPushButton("Choose File")
        choose_dir.clicked.connect(self._choose_directory)
        choose_file.clicked.connect(self._choose_file)
        self.suggest_button.clicked.connect(self.suggest_filename)
        output_buttons = QHBoxLayout()
        output_buttons.addWidget(choose_dir)
        output_buttons.addWidget(choose_file)
        output_buttons.addWidget(self.suggest_button)

        output_form = QFormLayout()
        output_form.addRow("Output directory", self.output_dir)
        output_form.addRow("Run filename", self.filename)
        output_form.addRow("Data backend (run override)", self.backend)
        output_form.addRow("Final path", self.final_path)

        layout = QVBoxLayout(self)
        layout.addLayout(sample_form)
        layout.addLayout(output_form)
        layout.addLayout(output_buttons)
        layout.addWidget(self.initialize_button)
        layout.addWidget(self.ready_label)

        self.initialize_button.clicked.connect(self.initializeRequested)
        for edit in (
            self.sample_id,
            self.material,
            self.operator,
            self.experiment_name,
            self.notebook,
            self.cooldown,
            self.contacts,
            self.orientation,
            self.output_dir,
            self.filename,
        ):
            edit.textChanged.connect(self._changed)
        self.notes.textChanged.connect(self._changed)
        self.backend.currentTextChanged.connect(self._changed)

    @property
    def output_path(self) -> Path | None:
        directory = self.output_dir.text().strip()
        filename = self.filename.text().strip()
        if not directory or not filename:
            return None
        return Path(directory) / filename

    def sample_metadata(self) -> SampleMetadata:
        return SampleMetadata(
            sample_id=self.sample_id.text().strip(),
            material=self.material.text().strip(),
            contact_configuration=self.contacts.text().strip(),
            orientation=self.orientation.text().strip(),
            notes=self.notes.toPlainText().strip(),
        )

    def run_metadata(self) -> RunMetadata:
        return RunMetadata(
            operator=self.operator.text().strip(),
            experiment_name=self.experiment_name.text().strip(),
            lab_notebook_reference=self.notebook.text().strip(),
            cooldown_id=self.cooldown.text().strip(),
        )

    def set_config(self, config: dict) -> None:
        metadata = config.get("sample_metadata", {})
        self.sample_id.setText(str(metadata.get("sample_id", "")))
        self.material.setText(str(metadata.get("material", metadata.get("description", ""))))
        self.operator.setText(str(metadata.get("operator", "")))
        self.experiment_name.setText(str(metadata.get("experiment_name", "")))
        self.notebook.setText(str(metadata.get("lab_notebook_reference", "")))
        self.cooldown.setText(str(metadata.get("cooldown_id", "")))
        self.contacts.setText(str(metadata.get("contact_configuration", "")))
        self.orientation.setText(str(metadata.get("orientation", "")))
        self.notes.setPlainText(str(metadata.get("notes", "")))
        data = config.get("data", {})
        self.output_dir.setText(str(Path(data.get("output_dir", ".")).resolve()))
        backend = str(data.get("backend", "multipyvu")).lower()
        index = self.backend.findText(backend)
        if index >= 0:
            self.backend.setCurrentIndex(index)
        self.suggest_filename()

    def suggest_filename(self) -> None:
        self.filename.setText(
            suggested_filename(self.sample_id.text(), self.experiment_name.text())
        )

    def set_initialized(self, ready: bool, message: str) -> None:
        self.ready_label.setText(message)
        self.initialize_button.setText("Run Ready" if ready else "Initialize Run")

    def set_locked(self, locked: bool) -> None:
        for widget in self.findChildren(QWidget):
            if widget is not self.ready_label:
                widget.setEnabled(not locked)

    def _choose_directory(self) -> None:
        selected = QFileDialog.getExistingDirectory(
            self, "Choose output directory", self.output_dir.text() or str(Path.cwd())
        )
        if selected:
            self.output_dir.setText(selected)

    def _choose_file(self) -> None:
        selected, _ = QFileDialog.getSaveFileName(
            self,
            "Choose output data file",
            str(self.output_path or (Path.cwd() / "run.dat")),
            "Data files (*.dat);;All files (*)",
        )
        if selected:
            path = Path(selected)
            self.output_dir.setText(str(path.parent))
            self.filename.setText(path.name)

    def _changed(self, *_args) -> None:
        path = self.output_path
        self.final_path.setText(str(path) if path else "Output path not selected")
        self.changed.emit()
