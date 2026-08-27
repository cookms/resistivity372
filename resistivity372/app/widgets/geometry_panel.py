from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QDoubleValidator
from PySide6.QtWidgets import (
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QWidget,
)

from resistivity372.core.exceptions import GeometryError
from resistivity372.core.geometry import (
    AREA_FACTORS_TO_M2,
    LENGTH_FACTORS_TO_M,
    SampleGeometry,
    geometry_from_config,
)


class GeometryPanel(QGroupBox):
    geometryChanged = Signal()

    def __init__(self, parent=None):
        super().__init__("Sample Geometry", parent)
        self.length_edit, self.length_unit = self._dimension_editor(LENGTH_FACTORS_TO_M)
        self.width_edit, self.width_unit = self._dimension_editor(LENGTH_FACTORS_TO_M)
        self.thickness_edit, self.thickness_unit = self._dimension_editor(LENGTH_FACTORS_TO_M)
        self.area_edit, self.area_unit = self._dimension_editor(AREA_FACTORS_TO_M2)
        self.status_label = QLabel("Resistivity calculation: unavailable - incomplete geometry")
        self.area_label = QLabel("Effective area: N/A")

        layout = QFormLayout(self)
        layout.addRow("Voltage-contact separation", self._pair(self.length_edit, self.length_unit))
        layout.addRow("Width", self._pair(self.width_edit, self.width_unit))
        layout.addRow("Thickness", self._pair(self.thickness_edit, self.thickness_unit))
        layout.addRow("Direct cross-sectional area", self._pair(self.area_edit, self.area_unit))
        layout.addRow(self.status_label)
        layout.addRow(self.area_label)

        for edit in (self.length_edit, self.width_edit, self.thickness_edit, self.area_edit):
            edit.textChanged.connect(self._changed)
        for combo in (self.length_unit, self.width_unit, self.thickness_unit, self.area_unit):
            combo.currentTextChanged.connect(self._changed)

    def set_config(self, config: dict) -> None:
        geom = config.get("sample_geometry", {})
        self._set_dimension(self.length_edit, self.length_unit, geom.get("length", {}), "m")
        self._set_dimension(self.width_edit, self.width_unit, geom.get("width", {}), "m")
        self._set_dimension(self.thickness_edit, self.thickness_unit, geom.get("thickness", {}), "m")
        self._set_dimension(self.area_edit, self.area_unit, geom.get("area", {}), "m^2")
        self._update_status()

    def geometry_config(self) -> dict:
        result = {}
        for name, edit, unit in (
            ("length", self.length_edit, self.length_unit),
            ("width", self.width_edit, self.width_unit),
            ("thickness", self.thickness_edit, self.thickness_unit),
            ("area", self.area_edit, self.area_unit),
        ):
            text = edit.text().strip()
            if text:
                try:
                    value = float(text)
                except ValueError as exc:
                    raise GeometryError(f"{name.capitalize()} must be a number.") from exc
                result[name] = {"value": value, "unit": unit.currentText()}
        return result

    def geometry(self) -> SampleGeometry:
        return geometry_from_config({"sample_geometry": self.geometry_config()})

    def validation_state(self) -> tuple[str, str]:
        try:
            geometry = self.geometry()
        except (GeometryError, ValueError) as exc:
            return "invalid", str(exc)
        if not geometry.has_geometry:
            return "missing", "Incomplete geometry; resistance will still be recorded."
        return "valid", "Resistivity calculation is enabled."

    def set_locked(self, locked: bool) -> None:
        for widget in (
            self.length_edit,
            self.length_unit,
            self.width_edit,
            self.width_unit,
            self.thickness_edit,
            self.thickness_unit,
            self.area_edit,
            self.area_unit,
        ):
            widget.setEnabled(not locked)

    def _changed(self, *_args) -> None:
        self._update_status()
        self.geometryChanged.emit()

    def _update_status(self) -> None:
        state, message = self.validation_state()
        if state == "valid":
            geometry = self.geometry()
            self.status_label.setText("Resistivity calculation: enabled")
            self.area_label.setText(f"Effective area: {geometry.effective_area_m2:.7g} m^2")
        elif state == "missing":
            self.status_label.setText("Resistivity calculation: unavailable - incomplete geometry")
            self.area_label.setText("Effective area: N/A")
        else:
            self.status_label.setText("Resistivity calculation: invalid - " + message)
            self.area_label.setText("Effective area: N/A")

    @staticmethod
    def _dimension_editor(units: dict[str, float]) -> tuple[QLineEdit, QComboBox]:
        edit = QLineEdit()
        validator = QDoubleValidator(edit)
        validator.setNotation(QDoubleValidator.Notation.ScientificNotation)
        edit.setValidator(validator)
        unit = QComboBox()
        unit.addItems(list(units))
        return edit, unit

    @staticmethod
    def _pair(edit: QLineEdit, unit: QComboBox) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit)
        layout.addWidget(unit)
        return widget

    @staticmethod
    def _set_dimension(edit: QLineEdit, unit: QComboBox, config: dict, default_unit: str) -> None:
        value = config.get("value")
        edit.setText("" if value is None else str(value))
        selected_unit = str(config.get("unit", default_unit))
        index = unit.findText(selected_unit)
        if index >= 0:
            unit.setCurrentIndex(index)
