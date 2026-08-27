from __future__ import annotations

import logging
from datetime import datetime

from PySide6.QtCore import QObject, Signal
from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget


class _LogEmitter(QObject):
    message = Signal(str)


class QtLogHandler(logging.Handler):
    def __init__(self, parent=None):
        super().__init__()
        self.emitter = _LogEmitter(parent)

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.emitter.message.emit(self.format(record))
        except Exception:
            self.handleError(record)


class LogPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.view = QPlainTextEdit()
        self.view.setReadOnly(True)
        self.view.setMaximumBlockCount(10_000)
        self.view.setFont(QFontDatabase.systemFont(QFontDatabase.SystemFont.FixedFont))
        clear = QPushButton("Clear Log")
        clear.clicked.connect(self.view.clear)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(clear)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(row)
        layout.addWidget(self.view)

    def append_message(self, message: str, level: str = "INFO") -> None:
        stamp = datetime.now().astimezone().strftime("%H:%M:%S")
        lines = str(message).rstrip().splitlines() or [""]
        self.view.appendPlainText(f"{stamp} [{level}] {lines[0]}")
        for line in lines[1:]:
            self.view.appendPlainText(f"             {line}")
        scrollbar = self.view.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def append_error(self, message: str) -> None:
        self.append_message(message, "ERROR")

    def make_logging_handler(self) -> QtLogHandler:
        handler = QtLogHandler(self)
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s: %(message)s"))
        handler.emitter.message.connect(lambda text: self.append_message(text, "PY"))
        return handler
