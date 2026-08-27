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
    assert (tmp_path / "gui_mock.dat").exists()
    assert len(window.plot_panel._records) == 6
    _shutdown(app, window)
