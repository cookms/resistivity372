from __future__ import annotations

from collections import deque

import pyqtgraph as pg
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


X_QUANTITIES = {
    "Elapsed Time": lambda r: r.elapsed_s,
    "PPMS Temperature": lambda r: r.ppms.temperature_K,
    "PPMS Field": lambda r: r.ppms.field_T,
}

Y_QUANTITIES = {
    "Resistance": lambda r: r.lakeshore.resistance_ohm,
    "Resistivity (Ohm m)": lambda r: r.resistivity_ohm_m,
    "Resistivity (Ohm cm)": lambda r: r.resistivity_ohm_cm,
    "Quadrature": lambda r: r.lakeshore.quadrature_ohm,
    "LS372 Temperature": lambda r: r.lakeshore.temperature_K,
}


class PlotPanel(QWidget):
    def __init__(self, max_points: int = 5000, parent=None):
        super().__init__(parent)
        self.max_points = max(100, int(max_points))
        self._records = deque(maxlen=self.max_points)
        self.x_combo = QComboBox()
        self.x_combo.addItems(X_QUANTITIES)
        self.y_combo = QComboBox()
        self.y_combo.addItems(Y_QUANTITIES)
        self.clear_button = QPushButton("Clear Plot")
        self.plot = pg.PlotWidget(background="w")
        self.plot.showGrid(x=True, y=True, alpha=0.25)
        self.curve = self.plot.plot([], [], pen=pg.mkPen("#1769aa", width=2), symbol=None)
        self.missing_label = QLabel("")

        controls = QHBoxLayout()
        controls.addWidget(QLabel("X"))
        controls.addWidget(self.x_combo)
        controls.addWidget(QLabel("Y"))
        controls.addWidget(self.y_combo)
        controls.addStretch(1)
        controls.addWidget(self.clear_button)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(controls)
        layout.addWidget(self.plot, 1)
        layout.addWidget(self.missing_label)

        self.x_combo.currentTextChanged.connect(self._refresh)
        self.y_combo.currentTextChanged.connect(self._refresh)
        self.clear_button.clicked.connect(self.clear)
        self._refresh()

    def add_record(self, record) -> None:
        self._records.append(record)
        self._refresh()

    def clear(self) -> None:
        self._records.clear()
        self.curve.setData([], [])
        self.missing_label.clear()

    def _refresh(self, *_args) -> None:
        x_name = self.x_combo.currentText()
        y_name = self.y_combo.currentText()
        x_get = X_QUANTITIES[x_name]
        y_get = Y_QUANTITIES[y_name]
        pairs = []
        missing = 0
        for record in self._records:
            x_value = x_get(record)
            y_value = y_get(record)
            if x_value is None or y_value is None:
                missing += 1
                continue
            pairs.append((float(x_value), float(y_value)))
        self.curve.setData(
            [pair[0] for pair in pairs],
            [pair[1] for pair in pairs],
        )
        self.plot.setLabel("bottom", x_name)
        self.plot.setLabel("left", y_name)
        self.plot.setTitle(f"{y_name} vs {x_name}")
        if missing and "Resistivity" in y_name:
            self.missing_label.setText(
                "Some points have no resistivity because sample geometry is incomplete."
            )
        else:
            self.missing_label.clear()
