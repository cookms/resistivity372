from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from PySide6.QtCore import Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from resistivity372.app.models import SequenceSummary, summarize_sequence
from resistivity372.core.safety import SafetyLimits
from resistivity372.measurement.sequence import parse_sequence
from resistivity372.measurement.sequence_runner import validate_sequence_against_safety


class SequenceEditor(QWidget):
    contentChanged = Signal()
    validationChanged = Signal(bool, str)
    sequenceLoaded = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.path_edit = QLineEdit()
        self.editor = QPlainTextEdit()
        self.editor.setLineWrapMode(QPlainTextEdit.LineWrapMode.NoWrap)
        self.editor.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        self.validation_label = QLabel("Sequence not validated")
        self.summary_view = QPlainTextEdit()
        self.summary_view.setReadOnly(True)
        self.summary_view.setMaximumHeight(145)
        self._loaded_text = ""
        self._validated_hash = ""
        self._summary: SequenceSummary | None = None

        browse = QPushButton("Choose")
        load = QPushButton("Load")
        reload_button = QPushButton("Reload")
        self.save_button = QPushButton("Save")
        save_as = QPushButton("Save As")
        self.validate_button = QPushButton("Validate")
        self._action_buttons = (browse, load, reload_button, self.save_button, save_as, self.validate_button)
        browse.clicked.connect(self._browse)
        load.clicked.connect(self.load)
        reload_button.clicked.connect(self.reload)
        self.save_button.clicked.connect(self.save)
        save_as.clicked.connect(self.save_as)

        path_row = QHBoxLayout()
        path_row.addWidget(QLabel("Sequence file"))
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        path_row.addWidget(load)
        path_row.addWidget(reload_button)
        path_row.addWidget(self.save_button)
        path_row.addWidget(save_as)
        path_row.addWidget(self.validate_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(path_row)
        layout.addWidget(self.editor, 1)
        layout.addWidget(self.validation_label)
        layout.addWidget(QLabel("Expanded sequence summary"))
        layout.addWidget(self.summary_view)

        self.editor.textChanged.connect(self._on_changed)
        self.path_edit.textChanged.connect(self._on_path_changed)

    @property
    def path(self) -> Path | None:
        text = self.path_edit.text().strip()
        return Path(text) if text else None

    @property
    def summary(self) -> SequenceSummary | None:
        return self._summary

    @property
    def is_dirty(self) -> bool:
        return self.editor.toPlainText() != self._loaded_text

    @property
    def is_validated_current(self) -> bool:
        return bool(self._validated_hash) and self._validated_hash == self._content_hash()

    @property
    def validation_fingerprint(self) -> str:
        return self._validated_hash

    @property
    def ready_for_run(self) -> bool:
        return bool(self.path and self.path.exists() and self.is_validated_current and not self.is_dirty)

    def set_path(self, path: str | Path, load: bool = True) -> None:
        self.path_edit.setText(str(path))
        if load:
            self.load()

    def load(self) -> bool:
        path = self.path
        if path is None:
            self._set_validation(False, "Choose a sequence file.")
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except Exception as exc:
            self._set_validation(False, f"Could not load sequence: {exc}")
            return False
        self.editor.blockSignals(True)
        self.editor.setPlainText(text)
        self.editor.blockSignals(False)
        self._loaded_text = text
        self._validated_hash = ""
        self._summary = None
        self.summary_view.clear()
        self._set_validation(False, "Loaded; validation required.")
        self.sequenceLoaded.emit(str(path))
        self.contentChanged.emit()
        return True

    def reload(self) -> None:
        self.load()

    def save(self) -> bool:
        path = self.path
        if path is None:
            return self.save_as()
        try:
            path.write_text(self.editor.toPlainText(), encoding="utf-8")
        except Exception as exc:
            self._set_validation(False, f"Could not save sequence: {exc}")
            return False
        self._loaded_text = self.editor.toPlainText()
        self.contentChanged.emit()
        return True

    def save_as(self) -> bool:
        selected, _ = QFileDialog.getSaveFileName(
            self, "Save sequence", str(self.path or Path.cwd()), "YAML files (*.yaml *.yml)"
        )
        if not selected:
            return False
        self.path_edit.setText(selected)
        return self.save()

    def validate_current(self, safety: SafetyLimits) -> tuple[bool, str]:
        try:
            raw = yaml.safe_load(self.editor.toPlainText())
            sequence = parse_sequence(raw, source="sequence editor")
            validate_sequence_against_safety(sequence, safety)
            self._summary = summarize_sequence(sequence)
            self._validated_hash = self._content_hash()
            message = "Sequence validation passed."
            if self.is_dirty:
                message += " Save the validated text before starting."
            self.summary_view.setPlainText(self._summary.to_text())
            self._set_validation(True, message)
            return True, message
        except Exception as exc:
            self._validated_hash = ""
            self._summary = None
            self.summary_view.clear()
            message = f"Sequence validation failed: {exc}"
            self._set_validation(False, message)
            return False, message

    def set_locked(self, locked: bool) -> None:
        self.editor.setReadOnly(locked)
        self.path_edit.setReadOnly(locked)
        for button in self._action_buttons:
            button.setEnabled(not locked)

    def _browse(self) -> None:
        selected, _ = QFileDialog.getOpenFileName(
            self, "Choose sequence", str(self.path or Path.cwd()), "YAML files (*.yaml *.yml)"
        )
        if selected:
            self.set_path(selected, load=True)

    def _on_changed(self) -> None:
        if not self.is_validated_current:
            self.validation_label.setText("Sequence changed; validation required.")
        self.contentChanged.emit()

    def _on_path_changed(self) -> None:
        self.contentChanged.emit()

    def _set_validation(self, valid: bool, message: str) -> None:
        self.validation_label.setText(message)
        self.validationChanged.emit(valid, message)

    def _content_hash(self) -> str:
        return hashlib.sha256(self.editor.toPlainText().encode("utf-8")).hexdigest()
