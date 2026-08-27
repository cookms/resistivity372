from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from resistivity372.core.safety import safety_from_config
from resistivity372.runtime import resolve_instrument_simulation_mode


class ConnectionPanel(QGroupBox):
    connectRequested = Signal()
    disconnectRequested = Signal()

    def __init__(self, parent=None):
        super().__init__("Instrument Configuration", parent)
        self._config: dict = {}
        self.lakeshore_mode = QLabel("LS372: not configured")
        self.ppms_mode = QLabel("PPMS: not configured")
        self.dry_run = QLabel("DRY RUN: unknown")
        self.backend = QLabel("Data backend: not configured")
        for label in (self.lakeshore_mode, self.ppms_mode, self.dry_run, self.backend):
            label.setStyleSheet("font-weight: 600;")

        self.lakeshore_settings = QLabel("N/A")
        self.ppms_settings = QLabel("N/A")
        self.lakeshore_state = QLabel("DISCONNECTED")
        self.ppms_state = QLabel("DISCONNECTED")
        self.safety_limits = QLabel("Load a configuration to view safety limits.")
        self.safety_limits.setWordWrap(True)

        form = QFormLayout()
        form.addRow("LS372 settings", self.lakeshore_settings)
        form.addRow("PPMS settings", self.ppms_settings)
        form.addRow("LS372 connection", self.lakeshore_state)
        form.addRow("PPMS connection", self.ppms_state)

        self.connect_button = QPushButton("Connect / Test")
        self.disconnect_button = QPushButton("Disconnect")
        self.connect_button.clicked.connect(self.connectRequested)
        self.disconnect_button.clicked.connect(self.disconnectRequested)
        buttons = QHBoxLayout()
        buttons.addWidget(self.connect_button)
        buttons.addWidget(self.disconnect_button)

        layout = QVBoxLayout(self)
        layout.addWidget(self.lakeshore_mode)
        layout.addWidget(self.ppms_mode)
        layout.addWidget(self.dry_run)
        layout.addWidget(self.backend)
        layout.addLayout(form)
        layout.addWidget(QLabel("Configured safety limits"))
        layout.addWidget(self.safety_limits)
        layout.addLayout(buttons)

    def set_config(self, config: dict) -> None:
        self._config = config
        simulation = resolve_instrument_simulation_mode(config)
        dry_run = bool(config.get("mode", {}).get("dry_run", False))
        backend = str(config.get("data", {}).get("backend", "multipyvu"))
        self.lakeshore_mode.setText(
            f"LS372: {'SIMULATED' if simulation.lakeshore else 'REAL'}"
        )
        self.ppms_mode.setText(f"PPMS: {'SIMULATED' if simulation.ppms else 'REAL'}")
        self.dry_run.setText(f"DRY RUN: {'ON' if dry_run else 'OFF'}")
        self.backend.setText(f"Data backend: {backend}")

        ls = config.get("lakeshore372", {}).get("connection", {})
        mode = str(ls.get("mode", "tcp")).upper()
        if mode == "TCP":
            detail = f"TCP {ls.get('ip_address', 'N/A')}:{ls.get('tcp_port', 7777)}"
        elif mode == "USB":
            detail = f"USB {ls.get('com_port') or ls.get('serial_number') or 'N/A'}"
        else:
            detail = f"GPIB {ls.get('gpib_resource') or ls.get('gpib_address') or 'N/A'}"
        self.lakeshore_settings.setText(detail)

        ppms = config.get("ppms", {})
        position = "position enabled" if ppms.get("use_position", False) else "position disabled"
        self.ppms_settings.setText(
            f"{ppms.get('host', '127.0.0.1')}:{ppms.get('port', 5000)}; {position}"
        )

        safety = safety_from_config(config)
        self.safety_limits.setText(
            f"Temperature {safety.temperature_min_K:g}-{safety.temperature_max_K:g} K; "
            f"max ramp {safety.temperature_rate_max_K_per_min:g} K/min\n"
            f"|Field| <= {safety.field_abs_max_T:g} T; "
            f"max ramp {safety.field_rate_max_T_per_min:g} T/min\n"
            f"Position {safety.position_min_deg:g} to {safety.position_max_deg:g} deg; "
            f"max rate {safety.position_rate_max_deg_per_s:g} deg/s"
        )

    def set_connection_state(self, states: dict) -> None:
        if "lakeshore" in states:
            self.lakeshore_state.setText(str(states["lakeshore"]).upper())
        if "ppms" in states:
            self.ppms_state.setText(str(states["ppms"]).upper())

    def set_controls_enabled(self, enabled: bool) -> None:
        self.connect_button.setEnabled(enabled)
        self.disconnect_button.setEnabled(enabled)
