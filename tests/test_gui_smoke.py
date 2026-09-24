import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")

from PySide6.QtWidgets import QApplication

from resistivity372.app.gui_main import MainWindow


def _wait_until(app, predicate, timeout_s=3.0):
    deadline = time.monotonic() + timeout_s
    while not predicate() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.01)
    return predicate()


def _shutdown(app, window):
    window._closing_pending = True
    window.shutdownRequested.emit()
    assert _wait_until(app, lambda: not window.worker_thread.isRunning())
    window._force_close = True
    window.close()


def test_main_window_instantiates_and_shuts_down_offscreen():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    assert window.worker_thread.isRunning()
    assert window.windowTitle()
    assert [window.workspace_tabs.tabText(index) for index in range(4)] == [
        "Run Setup & Status",
        "Sequence Builder",
        "Live Plot",
        "Application Log",
    ]
    assert window.workspace_tabs.indexOf(window.sequence_editor) == 1
    assert window.workspace_tabs.indexOf(window.plot_panel) == 2
    assert window.status_panel.selected_channel == 1

    requested_channels = []
    window.pollRequested.connect(requested_channels.append)
    window.status_panel.channel_selector.setValue(4)
    assert requested_channels[-1] == 4

    _shutdown(app, window)


def test_gui_runs_complete_mock_sequence(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    window.run_setup.output_dir.setText(str(tmp_path))
    window.run_setup.filename.setText("gui_mock.dat")
    window._validate_sequence()
    window._initialize_run()
    assert window.preparation.ready

    window._start()
    assert _wait_until(app, lambda: window.last_outcome != "", timeout_s=5.0)

    assert window.last_outcome == "completed"
    assert window.workspace_tabs.currentWidget() is window.plot_panel
    assert (tmp_path / "gui_mock.dat").exists()
    assert len(window.plot_panel._records) == 6
    _shutdown(app, window)


def test_composable_builder_orders_edits_and_generates_valid_yaml():
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    builder = window.sequence_editor.builder
    from resistivity372.app.sequence_blocks import (
        MeasureBlock,
        SetTemperatureBlock,
        WaitTemperatureBlock,
    )

    builder.clear()
    builder.add_block(SetTemperatureBlock(100.0, 2.0))
    builder.add_block(WaitTemperatureBlock(600.0))
    builder.add_block(MeasureBlock(points=20, duration_s=None))
    builder.edit_block(0, SetTemperatureBlock(50.0, 2.0))
    builder.block_list.setCurrentRow(2)
    builder.move_selected(-1)
    builder.duplicate_selected()
    assert len(builder.blocks) == 4
    builder.delete_selected()

    sequence = builder.generate()

    assert [block.KIND for block in builder.blocks] == [
        "set_temperature",
        "measure",
        "wait_temperature",
    ]
    assert sequence["metadata"]["composable_schema"] == 1
    assert "composable_blocks:" in window.sequence_editor.editor.toPlainText()
    assert window.sequence_editor.is_validated_current
    assert window.sequence_editor.is_dirty
    _shutdown(app, window)


def test_composable_builder_round_trips_through_sequence_editor_file(tmp_path):
    app = QApplication.instance() or QApplication([])
    window = MainWindow()
    builder = window.sequence_editor.builder
    from resistivity372.app.sequence_blocks import DelayBlock, SetFieldBlock, WaitFieldBlock

    builder.clear()
    expected = [SetFieldBlock(0.0, 0.1), WaitFieldBlock(600.0), DelayBlock(30.0)]
    for block in expected:
        builder.add_block(block)
    assert builder.generate() is not None

    path = tmp_path / "composed.yaml"
    window.sequence_editor.path_edit.setText(str(path))
    assert window.sequence_editor.save()
    builder.clear()
    assert window.sequence_editor.load()

    assert builder.blocks == expected
    assert window.sequence_editor.editor.toPlainText() == path.read_text(encoding="utf-8")
    _shutdown(app, window)
