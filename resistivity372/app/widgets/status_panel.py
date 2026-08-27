from __future__ import annotations

from PySide6.QtWidgets import QFormLayout, QGroupBox, QLabel, QTabWidget, QVBoxLayout, QWidget


class StatusPanel(QGroupBox):
    def __init__(self, parent=None):
        super().__init__("Live Instrument Status", parent)
        self._ppms_labels = self._make_labels(
            "connection",
            "temperature",
            "temperature_status",
            "field",
            "field_status",
            "chamber",
            "position",
            "position_status",
        )
        self._ls_labels = self._make_labels(
            "connection",
            "channel",
            "resistance",
            "temperature",
            "power",
            "current",
            "quadrature",
            "status",
        )
        tabs = QTabWidget()
        tabs.addTab(
            self._form_widget(
                self._ppms_labels,
                {
                    "connection": "Connection",
                    "temperature": "Temperature",
                    "temperature_status": "Temperature status",
                    "field": "Field",
                    "field_status": "Field status",
                    "chamber": "Chamber",
                    "position": "Position",
                    "position_status": "Position status",
                },
            ),
            "PPMS",
        )
        tabs.addTab(
            self._form_widget(
                self._ls_labels,
                {
                    "connection": "Connection",
                    "channel": "Channel",
                    "resistance": "Resistance",
                    "temperature": "LS372 temperature",
                    "power": "Excitation power",
                    "current": "Excitation current",
                    "quadrature": "Quadrature",
                    "status": "Reading status",
                },
            ),
            "Lake Shore 372",
        )
        layout = QVBoxLayout(self)
        layout.addWidget(tabs)

    def update_status(self, payload: dict) -> None:
        connections = payload.get("connections", {})
        if "ppms" in connections:
            self._ppms_labels["connection"].setText(str(connections["ppms"]))
        if "lakeshore" in connections:
            self._ls_labels["connection"].setText(str(connections["lakeshore"]))

        ppms = payload.get("ppms")
        if ppms is not None:
            self._ppms_labels["temperature"].setText(_number(ppms.temperature_K, " K"))
            self._ppms_labels["temperature_status"].setText(_value(ppms.temperature_status))
            self._ppms_labels["field"].setText(_number(ppms.field_T, " T"))
            self._ppms_labels["field_status"].setText(_value(ppms.field_status))
            self._ppms_labels["chamber"].setText(_value(ppms.chamber_status))
            self._ppms_labels["position"].setText(_number(ppms.position_deg, " deg"))
            self._ppms_labels["position_status"].setText(_value(ppms.position_status))

        lakeshore = payload.get("lakeshore")
        if lakeshore is not None:
            self._ls_labels["channel"].setText(str(lakeshore.channel))
            self._ls_labels["resistance"].setText(_number(lakeshore.resistance_ohm, " Ohm"))
            self._ls_labels["temperature"].setText(_number(lakeshore.temperature_K, " K"))
            self._ls_labels["power"].setText(_number(lakeshore.excitation_power_W, " W"))
            # The real controller currently does not populate excitation current.
            self._ls_labels["current"].setText(_number(lakeshore.excitation_current_A, " A"))
            self._ls_labels["quadrature"].setText(_number(lakeshore.quadrature_ohm, " Ohm"))
            self._ls_labels["status"].setText(_value(lakeshore.status))

        if payload.get("ppms_error"):
            self._ppms_labels["connection"].setText("ERROR: " + payload["ppms_error"])
        if payload.get("lakeshore_error"):
            self._ls_labels["connection"].setText("ERROR: " + payload["lakeshore_error"])

    @staticmethod
    def _make_labels(*names: str) -> dict[str, QLabel]:
        return {name: QLabel("N/A") for name in names}

    @staticmethod
    def _form_widget(labels: dict[str, QLabel], captions: dict[str, str]) -> QWidget:
        widget = QWidget()
        layout = QFormLayout(widget)
        for key, caption in captions.items():
            layout.addRow(caption, labels[key])
        return widget


def _number(value, suffix: str) -> str:
    if value is None:
        return "N/A"
    try:
        return f"{float(value):.7g}{suffix}"
    except (TypeError, ValueError):
        return "N/A"


def _value(value) -> str:
    return "N/A" if value is None else str(value)
