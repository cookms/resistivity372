from __future__ import annotations

from dataclasses import fields

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from resistivity372.app.models import summarize_sequence
from resistivity372.app.sequence_blocks import (
    BLOCK_TYPES,
    CommentBlock,
    DelayBlock,
    FieldEquilibrationBlock,
    MeasureBlock,
    RawStepBlock,
    RhoVsFieldContinuousBlock,
    RhoVsFieldSteppedBlock,
    RhoVsTemperatureContinuousBlock,
    RhoVsTemperatureSteppedBlock,
    SequenceBlock,
    SetChamberBlock,
    SetFieldBlock,
    SetTemperatureBlock,
    TemperatureEquilibrationBlock,
    WaitFieldBlock,
    WaitChamberBlock,
    WaitTemperatureBlock,
    blocks_from_sequence,
    blocks_to_sequence,
)
from resistivity372.core.safety import SafetyLimits

ADDABLE_BLOCKS = (
    SetTemperatureBlock,
    WaitTemperatureBlock,
    TemperatureEquilibrationBlock,
    SetFieldBlock,
    WaitFieldBlock,
    FieldEquilibrationBlock,
    SetChamberBlock,
    WaitChamberBlock,
    DelayBlock,
    CommentBlock,
    MeasureBlock,
    RhoVsTemperatureSteppedBlock,
    RhoVsTemperatureContinuousBlock,
    RhoVsFieldSteppedBlock,
    RhoVsFieldContinuousBlock,
)

FIELD_LABELS = {
    "setpoint_K": "Temperature setpoint (K)",
    "rate_K_per_min": "Temperature ramp rate (K/min)",
    "setpoint_T": "Field setpoint (T)",
    "rate_T_per_min": "Field ramp rate (T/min)",
    "timeout_s": "Stability / sweep timeout (s)",
    "duration_s": "Duration (s)",
    "text": "Comment / marker text",
    "channel": "Measurement channel",
    "interval_s": "Measurement interval (s)",
    "points": "Measurement points (0 = not set)",
    "start_K": "Temperature start (K)",
    "stop_K": "Temperature stop (K)",
    "step_K": "Temperature step (K)",
    "equilibration_s": "Equilibration after stable (s)",
    "initial_equilibration_s": "Initial equilibration after stable (s)",
    "tolerance_K": "Target tolerance (K)",
    "stable_s": "Must remain within tolerance (s)",
    "poll_s": "Status polling interval (s)",
    "read_delay_s": "No field reads after command (s)",
    "field_read_delay_s": "No field reads after command (s)",
    "stable_at_target_s": "Stable at target for (s)",
    "endpoint_equilibration_s": "Endpoint equilibration after stable (s)",
    "start_T": "Field start (T)",
    "stop_T": "Field stop (T)",
    "step_T": "Field step (T)",
    "tolerance_T": "Target tolerance (T)",
}

OPTIONAL_NUMBERS = {"points", "duration_s"}
ACQUISITION_BLOCKS = (MeasureBlock, RhoVsTemperatureSteppedBlock, RhoVsFieldSteppedBlock)


class SequenceBuilderPanel(QWidget):
    sequenceGenerated = Signal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.safety = SafetyLimits()
        self.blocks: list[SequenceBlock] = []
        self._editors: dict[str, dict[str, QWidget]] = {}
        self._page_index: dict[str, int] = {}

        self.block_type = QComboBox()
        for cls in ADDABLE_BLOCKS:
            self.block_type.addItem(cls.LABEL, cls.KIND)

        self.pages = QStackedWidget()
        for cls in ADDABLE_BLOCKS:
            self._page_index[cls.KIND] = self.pages.count()
            self.pages.addWidget(self._make_editor_page(cls))

        self.block_list = QListWidget()
        self.block_list.setAlternatingRowColors(True)
        self.block_list.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.block_list.currentRowChanged.connect(self._load_selected)
        self.block_list.itemDoubleClicked.connect(
            lambda _item: self._load_selected(self.block_list.currentRow())
        )

        add_button = QPushButton("Add Block")
        self.update_button = QPushButton("Apply Changes")
        up_button = QPushButton("Move Up")
        down_button = QPushButton("Move Down")
        duplicate_button = QPushButton("Duplicate")
        delete_button = QPushButton("Delete")
        generate_button = QPushButton("Generate / Preview YAML")

        add_button.clicked.connect(self.add_current_block)
        self.update_button.clicked.connect(self.update_selected_block)
        up_button.clicked.connect(lambda: self.move_selected(-1))
        down_button.clicked.connect(lambda: self.move_selected(1))
        duplicate_button.clicked.connect(self.duplicate_selected)
        delete_button.clicked.connect(self.delete_selected)
        generate_button.clicked.connect(self.generate)
        self.block_type.currentIndexChanged.connect(self._show_selected_type)

        list_buttons = QHBoxLayout()
        for button in (up_button, down_button, duplicate_button, delete_button):
            list_buttons.addWidget(button)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.addWidget(QLabel("Experiment blocks — execution order"))
        left_layout.addWidget(self.block_list, 1)
        left_layout.addLayout(list_buttons)

        chooser = QHBoxLayout()
        chooser.addWidget(QLabel("Block type"))
        chooser.addWidget(self.block_type, 1)
        editor_buttons = QHBoxLayout()
        editor_buttons.addWidget(add_button)
        editor_buttons.addWidget(self.update_button)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.addLayout(chooser)
        right_layout.addWidget(self.pages)
        right_layout.addLayout(editor_buttons)
        right_layout.addStretch(1)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([700, 520])

        self.message = QLabel("Add blocks in the order the PPMS should execute them.")
        self.message.setWordWrap(True)
        self.preview = QLabel("")
        self.preview.setWordWrap(True)
        self.preview.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.addWidget(splitter, 1)
        layout.addWidget(generate_button)
        layout.addWidget(self.message)
        layout.addWidget(QLabel("Expanded experiment summary"))
        layout.addWidget(self.preview)

        self._show_selected_type()
        self._refresh_list()

    def set_safety_limits(self, safety: SafetyLimits) -> None:
        self.safety = safety
        for editors in self._editors.values():
            for name, editor in editors.items():
                if not isinstance(editor, QDoubleSpinBox):
                    continue
                if name in {"setpoint_K", "start_K", "stop_K"}:
                    editor.setRange(safety.temperature_min_K, safety.temperature_max_K)
                elif name == "rate_K_per_min":
                    editor.setRange(0.000001, safety.temperature_rate_max_K_per_min)
                elif name in {"setpoint_T", "start_T", "stop_T"}:
                    editor.setRange(-safety.field_abs_max_T, safety.field_abs_max_T)
                elif name == "rate_T_per_min":
                    editor.setRange(0.000001, safety.field_rate_max_T_per_min)

    def add_block(self, block: SequenceBlock, index: int | None = None) -> None:
        if index is None:
            self.blocks.append(block)
            row = len(self.blocks) - 1
        else:
            row = max(0, min(index, len(self.blocks)))
            self.blocks.insert(row, block)
        self._refresh_list(row)

    def edit_block(self, index: int, block: SequenceBlock) -> None:
        if index < 0 or index >= len(self.blocks):
            raise IndexError("Block index out of range.")
        self.blocks[index] = block
        self._refresh_list(index)

    def add_current_block(self) -> None:
        try:
            self.add_block(self._block_from_form())
            self.message.setText("Block added. Generate YAML when the experiment is ready.")
        except Exception as exc:
            self.message.setText(f"Cannot add block: {exc}")

    def update_selected_block(self) -> None:
        row = self.block_list.currentRow()
        if row < 0:
            self.message.setText("Select a block to edit.")
            return
        try:
            self.edit_block(row, self._block_from_form())
            self.message.setText("Selected block updated.")
        except Exception as exc:
            self.message.setText(f"Cannot update block: {exc}")

    def move_selected(self, offset: int) -> None:
        row = self.block_list.currentRow()
        target = row + offset
        if row < 0 or target < 0 or target >= len(self.blocks):
            return
        self.blocks[row], self.blocks[target] = self.blocks[target], self.blocks[row]
        self._refresh_list(target)

    def duplicate_selected(self) -> None:
        row = self.block_list.currentRow()
        if row < 0:
            return
        values = {key: value for key, value in self.blocks[row].to_dict().items() if key != "type"}
        duplicate = BLOCK_TYPES[self.blocks[row].KIND](**values)
        self.blocks.insert(row + 1, duplicate)
        self._refresh_list(row + 1)

    def delete_selected(self) -> None:
        row = self.block_list.currentRow()
        if row < 0:
            return
        del self.blocks[row]
        self._refresh_list(min(row, len(self.blocks) - 1))

    def clear(self) -> None:
        self.blocks.clear()
        self._refresh_list()
        self.preview.clear()

    def load_sequence(self, sequence: dict) -> None:
        self.blocks = blocks_from_sequence(sequence)
        self._refresh_list(0 if self.blocks else -1)
        self.message.setText(
            "Loaded blocks from YAML. Unsupported operations are preserved as read-only YAML steps."
        )

    def generate(self) -> dict | None:
        try:
            sequence = blocks_to_sequence(self.blocks, self.safety)
            self.preview.setText(summarize_sequence(sequence).to_text())
            self.message.setText(
                "Expanded sequence passed configured safety validation. Review, save, and "
                "validate the YAML before initializing a run."
            )
            self.sequenceGenerated.emit(sequence)
            return sequence
        except Exception as exc:
            self.preview.clear()
            self.message.setText(f"Cannot generate sequence: {exc}")
            return None

    def _make_editor_page(self, cls: type[SequenceBlock]) -> QWidget:
        page = QWidget()
        form = QFormLayout(page)
        editors: dict[str, QWidget] = {}
        default = cls()
        for field in fields(default):
            value = getattr(default, field.name)
            optional = isinstance(default, ACQUISITION_BLOCKS) and field.name in OPTIONAL_NUMBERS
            editor = _field_editor(field.name, value, optional)
            editors[field.name] = editor
            label = FIELD_LABELS.get(field.name, field.name.replace("_", " ").title())
            form.addRow(label, editor)
        self._editors[cls.KIND] = editors
        return page

    def _show_selected_type(self) -> None:
        kind = self.block_type.currentData()
        if kind in self._page_index:
            self.pages.setCurrentIndex(self._page_index[kind])
        self.update_button.setEnabled(self.block_list.currentRow() >= 0)

    def _block_from_form(self) -> SequenceBlock:
        kind = str(self.block_type.currentData())
        cls = BLOCK_TYPES[kind]
        values = {name: _editor_value(name, editor) for name, editor in self._editors[kind].items()}
        return cls(**values)

    def _load_selected(self, row: int) -> None:
        self.update_button.setEnabled(row >= 0)
        if row < 0 or row >= len(self.blocks):
            return
        block = self.blocks[row]
        combo_index = self.block_type.findData(block.KIND)
        if combo_index < 0 or isinstance(block, RawStepBlock):
            self.message.setText(
                "This imported YAML operation is preserved exactly but must be edited in the YAML tab."
            )
            self.update_button.setEnabled(False)
            return
        self.block_type.setCurrentIndex(combo_index)
        for name, editor in self._editors[block.KIND].items():
            _set_editor_value(editor, getattr(block, name))

    def _refresh_list(self, selected_row: int = -1) -> None:
        self.block_list.blockSignals(True)
        self.block_list.clear()
        for index, block in enumerate(self.blocks, start=1):
            self.block_list.addItem(f"{index:02d}   {block.summary()}")
        self.block_list.blockSignals(False)
        if self.blocks and selected_row >= 0:
            self.block_list.setCurrentRow(min(selected_row, len(self.blocks) - 1))
            self._load_selected(self.block_list.currentRow())
        else:
            self.update_button.setEnabled(False)


def _field_editor(name: str, value, optional: bool = False) -> QWidget:
    if isinstance(value, str):
        return QLineEdit(value)
    if name in {"channel", "points"}:
        editor = QSpinBox()
        editor.setRange(0 if name == "points" else 1, 1_000_000 if name == "points" else 64)
        editor.setValue(int(value or 0))
        if name == "points":
            editor.setSpecialValueText("Not set")
            editor.setProperty("optional_number", optional)
        return editor
    editor = QDoubleSpinBox()
    editor.setDecimals(6)
    editor.setKeyboardTracking(False)
    if name in {"start_T", "stop_T", "setpoint_T"}:
        editor.setRange(-100.0, 100.0)
    elif (
        optional
        or "equilibration" in name
        or "stable_at" in name
        or name in {"stable_s", "read_delay_s", "field_read_delay_s"}
    ):
        editor.setRange(0.0, 1_000_000.0)
        editor.setSpecialValueText("Not set" if optional else "0")
    else:
        editor.setRange(0.000001, 1_000_000.0)
    editor.setValue(float(value or 0.0))
    editor.setProperty("optional_number", optional)
    return editor


def _editor_value(name: str, editor: QWidget):
    if isinstance(editor, QLineEdit):
        return editor.text()
    value = editor.value()
    if editor.property("optional_number") and value == 0:
        return None
    return int(value) if isinstance(editor, QSpinBox) else float(value)


def _set_editor_value(editor: QWidget, value) -> None:
    if isinstance(editor, QLineEdit):
        editor.setText(str(value or ""))
    else:
        editor.setValue(value or 0)
