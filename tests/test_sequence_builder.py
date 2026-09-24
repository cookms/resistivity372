import threading
import time

import pytest
import yaml

from resistivity372.app.sequence_builder import (
    build_continuous_field_sequence,
    build_continuous_temperature_sequence,
    build_stepped_field_sequence,
    build_stepped_temperature_sequence,
    inclusive_setpoints,
)
from resistivity372.core.exceptions import InstrumentTimeoutError, SequenceValidationError
from resistivity372.core.geometry import SampleGeometry
from resistivity372.core.safety import SafetyLimits
from resistivity372.instruments.mocks import MockLakeShore372Controller, MockPPMSController
from resistivity372.measurement.engine import ResistivityMeasurementEngine
from resistivity372.measurement.sequence import parse_sequence
from resistivity372.measurement.sequence_runner import (
    SequenceRunner,
    validate_sequence_against_safety,
)

SAFETY = SafetyLimits(
    temperature_min_K=1.8,
    temperature_max_K=350.0,
    temperature_rate_max_K_per_min=5.0,
    field_abs_max_T=9.0,
    field_rate_max_T_per_min=0.25,
)


def _measure_kwargs():
    return {
        "channel": 1,
        "interval_s": 0.001,
        "points": 2,
        "duration_s": None,
        "timeout_s": 2.0,
    }


def test_direction_aware_setpoints_include_grid_endpoints():
    assert inclusive_setpoints(2, 6, 2) == [2.0, 4.0, 6.0]
    assert inclusive_setpoints(6, 2, 2) == [6.0, 4.0, 2.0]
    assert inclusive_setpoints(-1, 1, 1) == [-1.0, 0.0, 1.0]
    assert inclusive_setpoints(1, -1, 1) == [1.0, 0.0, -1.0]


@pytest.mark.parametrize(
    ("start", "stop", "expected"),
    [(2.0, 6.0, [2.0, 4.0, 6.0]), (6.0, 2.0, [6.0, 4.0, 2.0])],
)
def test_stepped_temperature_sequence_direction_and_multiple_fields(start, stop, expected):
    sequence = build_stepped_temperature_sequence(
        safety=SAFETY,
        field_values_T=[0.0, 1.0, 3.0],
        field_rate_T_per_min=0.1,
        temperature_start_K=start,
        temperature_stop_K=stop,
        temperature_step_K=2.0,
        temperature_rate_K_per_min=2.0,
        equilibration_s=0.0,
        **_measure_kwargs(),
    )

    fields = [step["set_field"]["setpoint_T"] for step in sequence["steps"] if "set_field" in step]
    temperatures = [
        step["set_temperature"]["setpoint_K"]
        for step in sequence["steps"]
        if "set_temperature" in step
    ]
    assert fields == [0.0, 1.0, 3.0]
    assert temperatures == expected * 3
    assert all(
        step["set_temperature"]["wait"] for step in sequence["steps"] if "set_temperature" in step
    )


@pytest.mark.parametrize(
    ("start", "stop", "expected"),
    [(-1.0, 1.0, [-1.0, 0.0, 1.0]), (1.0, -1.0, [1.0, 0.0, -1.0])],
)
def test_stepped_field_sequence_direction(start, stop, expected):
    sequence = build_stepped_field_sequence(
        safety=SAFETY,
        fixed_temperature_K=10.0,
        temperature_rate_K_per_min=2.0,
        field_start_T=start,
        field_stop_T=stop,
        field_step_T=1.0,
        field_rate_T_per_min=0.1,
        equilibration_s=0.0,
        **_measure_kwargs(),
    )
    fields = [step["set_field"]["setpoint_T"] for step in sequence["steps"] if "set_field" in step]
    assert fields == expected


def test_continuous_temperature_representation_and_yaml_round_trip():
    sequence = build_continuous_temperature_sequence(
        safety=SAFETY,
        field_values_T=[0.0, 3.0],
        field_rate_T_per_min=0.1,
        temperature_start_K=300.0,
        temperature_stop_K=2.0,
        temperature_rate_K_per_min=2.0,
        initial_equilibration_s=0.0,
        channel=2,
        interval_s=0.5,
        target_tolerance_K=0.05,
        target_settle_s=1.0,
        timeout_s=20_000.0,
    )
    continuous = [step["measure_until"] for step in sequence["steps"] if "measure_until" in step]
    assert len(continuous) == 2
    assert all(step["quantity"] == "temperature" for step in continuous)
    assert all(step["target"] == 2.0 for step in continuous)
    assert all(step["require_stable"] is False for step in continuous)

    loaded = yaml.safe_load(yaml.safe_dump(sequence, sort_keys=False))
    assert parse_sequence(loaded) == sequence
    validate_sequence_against_safety(loaded, SAFETY)


def test_continuous_field_representation_supports_decreasing_sweep():
    sequence = build_continuous_field_sequence(
        safety=SAFETY,
        fixed_temperature_K=10.0,
        temperature_rate_K_per_min=2.0,
        field_start_T=9.0,
        field_stop_T=-9.0,
        field_rate_T_per_min=0.2,
        initial_equilibration_s=0.0,
        channel=1,
        interval_s=0.25,
        target_tolerance_T=0.001,
        target_settle_s=0.0,
        timeout_s=20_000.0,
    )
    field_commands = [step["set_field"] for step in sequence["steps"] if "set_field" in step]
    continuous = next(
        step["measure_until"] for step in sequence["steps"] if "measure_until" in step
    )
    assert [command["setpoint_T"] for command in field_commands] == [9.0, -9.0]
    assert field_commands[0]["wait"] is True
    assert field_commands[1]["wait"] is False
    assert continuous["quantity"] == "field"
    assert continuous["target"] == -9.0


def test_builder_rejects_safety_limit_violation():
    with pytest.raises(SequenceValidationError, match="Invalid expanded step"):
        build_stepped_temperature_sequence(
            safety=SAFETY,
            field_values_T=[10.0],
            field_rate_T_per_min=0.1,
            temperature_start_K=2.0,
            temperature_stop_K=4.0,
            temperature_step_K=1.0,
            temperature_rate_K_per_min=2.0,
            equilibration_s=0.0,
            **_measure_kwargs(),
        )


class MemoryDataFile:
    def __init__(self):
        self.records = []

    @property
    def is_open(self):
        return True

    def write_record(self, record):
        self.records.append(record)


def _runner(ppms, datafile, abort=None):
    lakeshore = MockLakeShore372Controller(noise_ohm=0.0)
    lakeshore.connect()
    ppms.connect()
    abort = abort or threading.Event()
    pause = threading.Event()
    engine = ResistivityMeasurementEngine(
        lakeshore=lakeshore,
        ppms=ppms,
        datafile=datafile,
        geometry=SampleGeometry(),
        abort_flag=abort,
        pause_flag=pause,
    )
    return SequenceRunner(
        ppms=ppms,
        lakeshore=lakeshore,
        engine=engine,
        safety=SAFETY,
        abort_flag=abort,
        pause_flag=pause,
    )


def test_continuous_temperature_acquires_actual_ramping_status_until_stable():
    sequence = build_continuous_temperature_sequence(
        safety=SAFETY,
        field_values_T=[0.0],
        field_rate_T_per_min=0.1,
        temperature_start_K=10.0,
        temperature_stop_K=20.0,
        temperature_rate_K_per_min=2.0,
        initial_equilibration_s=0.0,
        channel=1,
        interval_s=0.001,
        target_tolerance_K=0.001,
        target_settle_s=0.0,
        timeout_s=2.0,
    )
    datafile = MemoryDataFile()
    runner = _runner(MockPPMSController(safety=SAFETY, ramp_readings=5), datafile)
    runner.run(sequence)

    temperatures = [record.ppms.temperature_K for record in datafile.records]
    assert len(temperatures) == 5
    assert temperatures == sorted(temperatures)
    assert temperatures[-1] == 20.0
    assert datafile.records[-1].ppms.temperature_status == "stable"


def test_continuous_field_acquires_actual_ramping_status_until_stable():
    sequence = build_continuous_field_sequence(
        safety=SAFETY,
        fixed_temperature_K=10.0,
        temperature_rate_K_per_min=2.0,
        field_start_T=-1.0,
        field_stop_T=1.0,
        field_rate_T_per_min=0.1,
        initial_equilibration_s=0.0,
        channel=1,
        interval_s=0.001,
        target_tolerance_T=0.0001,
        target_settle_s=0.0,
        timeout_s=2.0,
    )
    datafile = MemoryDataFile()
    runner = _runner(MockPPMSController(safety=SAFETY, ramp_readings=4), datafile)
    runner.run(sequence)

    fields = [record.ppms.field_T for record in datafile.records]
    assert len(fields) == 4
    assert fields == sorted(fields)
    assert fields[-1] == 1.0
    assert datafile.records[-1].ppms.field_status == "stable"


def test_cooperative_abort_stops_continuous_acquisition():
    abort = threading.Event()
    datafile = MemoryDataFile()
    ppms = MockPPMSController(safety=SAFETY)
    runner = _runner(ppms, datafile, abort)
    result = []
    thread = threading.Thread(
        target=lambda: result.append(
            runner.engine.measure_until(
                channel=1,
                interval_s=0.005,
                quantity="temperature",
                target=2.0,
                tolerance=0.001,
                timeout_s=10.0,
            )
        )
    )
    thread.start()
    time.sleep(0.04)
    abort.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()
    assert result[0] == len(datafile.records)
    assert result[0] > 0


def test_continuous_acquisition_has_timeout_protection():
    datafile = MemoryDataFile()
    ppms = MockPPMSController(safety=SAFETY)
    runner = _runner(ppms, datafile)

    with pytest.raises(InstrumentTimeoutError, match="did not reach stable temperature"):
        runner.engine.measure_until(
            channel=1,
            interval_s=0.002,
            quantity="temperature",
            target=2.0,
            tolerance=0.001,
            timeout_s=0.02,
        )

    assert datafile.records
