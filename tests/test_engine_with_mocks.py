import csv
import threading
import time

from resistivity372.core.geometry import SampleGeometry
from resistivity372.core.safety import SafetyLimits
from resistivity372.instruments.mocks import MockLakeShore372Controller, MockPPMSController
from resistivity372.measurement.datafile_manager import CsvDataFileManager
from resistivity372.measurement.engine import ResistivityMeasurementEngine


def test_engine_writes_n_points(tmp_path):
    ls = MockLakeShore372Controller(base_resistance_ohm=100.0, noise_ohm=0.0)
    ppms = MockPPMSController(safety=SafetyLimits())
    ls.connect()
    ppms.connect()

    datafile = CsvDataFileManager()
    path = tmp_path / "test.dat"
    datafile.create(path, metadata={"test": True})

    records = []
    engine = ResistivityMeasurementEngine(
        lakeshore=ls,
        ppms=ppms,
        datafile=datafile,
        geometry=SampleGeometry(length_m=1e-3, area_m2=1e-8),
        abort_flag=threading.Event(),
        pause_flag=threading.Event(),
        on_record=records.append,
    )
    count = engine.measure(channel=1, interval_s=0.001, points=3, step_name="test")
    datafile.close()

    assert count == 3
    assert len(records) == 3
    assert records[0].resistivity_ohm_m is not None

    with path.open("r", encoding="utf-8") as handle:
        rows = [line for line in handle.readlines() if not line.startswith("#")]
    parsed = list(csv.DictReader(rows))
    assert len(parsed) == 3
    assert parsed[0]["Sequence Step Name"] == "test"


class MemoryDataFile:
    def __init__(self):
        self.records = []

    @property
    def is_open(self):
        return True

    def write_record(self, record):
        self.records.append(record)


def test_engine_pause_resume_and_cooperative_abort():
    ls = MockLakeShore372Controller(noise_ohm=0.0)
    ppms = MockPPMSController(safety=SafetyLimits())
    ls.connect()
    ppms.connect()
    pause = threading.Event()
    abort = threading.Event()
    pause.set()
    datafile = MemoryDataFile()
    engine = ResistivityMeasurementEngine(
        lakeshore=ls,
        ppms=ppms,
        datafile=datafile,
        geometry=SampleGeometry(),
        abort_flag=abort,
        pause_flag=pause,
    )
    result = []
    thread = threading.Thread(
        target=lambda: result.append(engine.measure(channel=1, interval_s=0.005, points=1000))
    )
    thread.start()
    time.sleep(0.03)
    assert datafile.records == []
    pause.clear()
    time.sleep(0.04)
    abort.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert 0 < result[0] < 1000
