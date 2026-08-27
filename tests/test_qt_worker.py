import os
from types import SimpleNamespace

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication

from resistivity372.app.qt_worker import MeasurementWorker
from resistivity372.runtime import RuntimeFactory


def _config():
    return {
        "mode": {"simulation": True, "dry_run": True},
        "lakeshore372": {"simulation": True},
        "ppms": {"simulation": True},
        "data": {"backend": "csv", "allow_overwrite": False},
        "sample_geometry": {
            "length": {"value": 1.0, "unit": "mm"},
            "area": {"value": 0.01, "unit": "mm^2"},
        },
        "safety": {
            "temperature_min_K": 1.8,
            "temperature_max_K": 350.0,
            "temperature_rate_max_K_per_min": 5.0,
            "field_abs_max_T": 9.0,
            "field_rate_max_T_per_min": 0.25,
            "allowed_chamber_modes": ["seal"],
            "position_min_deg": -180.0,
            "position_max_deg": 180.0,
            "position_rate_max_deg_per_s": 5.0,
        },
    }


class CapturingFactory(RuntimeFactory):
    def create_bundle(self, *args, **kwargs):
        bundle = super().create_bundle(*args, **kwargs)
        self.last_bundle = bundle
        return bundle


def test_worker_runs_mock_sequence_emits_records_and_cleans_up(tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    factory = CapturingFactory()
    worker = MeasurementWorker(factory)
    records = []
    finished = []
    outcomes = []
    worker.recordReady.connect(records.append)
    worker.finished.connect(lambda: finished.append(True))
    worker.runOutcome.connect(outcomes.append)

    worker.start_run(
        _config(),
        "sequences/smoke_simulation.yaml",
        str(tmp_path / "worker.dat"),
        {"test": True},
    )

    assert records
    assert finished == [True]
    assert outcomes == ["completed"]
    assert factory.last_bundle.datafile.is_open is False
    assert factory.last_bundle.controllers.lakeshore.is_connected is False
    assert factory.last_bundle.controllers.ppms.is_connected is False


class FailingRunner:
    def run(self, sequence):
        raise RuntimeError("runner exploded")


class Resource:
    def __init__(self):
        self.closed = False

    def close(self):
        self.closed = True


class Controller:
    def __init__(self):
        self.disconnected = False

    def disconnect(self):
        self.disconnected = True


class FailingFactory:
    def __init__(self):
        self.datafile = Resource()
        self.lakeshore = Controller()
        self.ppms = Controller()

    def create_bundle(self, **kwargs):
        return SimpleNamespace(
            datafile=self.datafile,
            controllers=SimpleNamespace(lakeshore=self.lakeshore, ppms=self.ppms),
            runner=FailingRunner(),
        )


def test_worker_emits_error_and_cleans_up_after_failure(tmp_path):
    QCoreApplication.instance() or QCoreApplication([])
    factory = FailingFactory()
    worker = MeasurementWorker(factory)
    errors = []
    finished = []
    worker.errorMessage.connect(errors.append)
    worker.finished.connect(lambda: finished.append(True))

    worker.start_run(
        _config(),
        "sequences/smoke_simulation.yaml",
        str(tmp_path / "failure.dat"),
        {},
    )

    assert errors == ["runner exploded"]
    assert finished == [True]
    assert factory.datafile.closed is True
    assert factory.lakeshore.disconnected is True
    assert factory.ppms.disconnected is True
