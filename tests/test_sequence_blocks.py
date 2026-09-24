import threading
import time

import yaml

from resistivity372.app.sequence_blocks import (
    CommentBlock,
    DelayBlock,
    FieldEquilibrationBlock,
    MeasureBlock,
    RhoVsFieldContinuousBlock,
    RhoVsTemperatureContinuousBlock,
    RhoVsTemperatureSteppedBlock,
    SetFieldBlock,
    SetTemperatureBlock,
    TemperatureEquilibrationBlock,
    WaitFieldBlock,
    WaitTemperatureBlock,
    block_from_dict,
    blocks_from_sequence,
    blocks_to_sequence,
)
from resistivity372.core.geometry import SampleGeometry
from resistivity372.core.safety import SafetyLimits
from resistivity372.instruments.mocks import MockLakeShore372Controller, MockPPMSController
from resistivity372.measurement.engine import ResistivityMeasurementEngine
from resistivity372.measurement.sequence import parse_sequence
from resistivity372.measurement.sequence_runner import SequenceRunner

SAFETY = SafetyLimits(
    temperature_min_K=1.8,
    temperature_max_K=350.0,
    temperature_rate_max_K_per_min=5.0,
    field_abs_max_T=9.0,
    field_rate_max_T_per_min=0.25,
)


def test_primitive_block_order_and_explicit_post_stability_equilibration():
    blocks = [
        SetTemperatureBlock(10.0, 2.0),
        WaitTemperatureBlock(600.0),
        TemperatureEquilibrationBlock(300.0),
        MeasureBlock(points=20, duration_s=None),
    ]

    sequence = blocks_to_sequence(blocks, SAFETY)

    operations = [_operation(step) for step in sequence["steps"]]
    assert operations == ["set_temperature", "wait_temperature", "delay", "measure"]
    assert sequence["steps"][0]["set_temperature"]["wait"] is False
    assert sequence["steps"][1]["wait_temperature"]["stable_s"] == 10.0
    assert sequence["steps"][1]["wait_temperature"]["equilibration_s"] == 0.0
    assert sequence["steps"][2]["delay"]["duration_s"] == 300.0


def test_block_editing_serialization_and_deserialization():
    original = SetFieldBlock(setpoint_T=-3.0, rate_T_per_min=0.1)
    serialized = original.to_dict()
    restored = block_from_dict(serialized)
    edited = SetFieldBlock(setpoint_T=3.0, rate_T_per_min=restored.rate_T_per_min)

    assert restored == original
    assert edited.summary() == "Set Field — 3 T @ 0.1 T/min"
    assert edited.expand()[0]["set_field"]["setpoint_T"] == 3.0


def test_high_level_temperature_block_expands_to_executable_steps():
    block = RhoVsTemperatureSteppedBlock(
        start_K=6.0,
        stop_K=2.0,
        step_K=2.0,
        rate_K_per_min=2.0,
        equilibration_s=15.0,
        timeout_s=600.0,
        channel=2,
        interval_s=0.5,
        points=3,
    )

    steps = block.expand()

    assert [_operation(step) for step in steps] == [
        "set_temperature",
        "wait_temperature",
        "measure",
    ] * 3
    waits = [step["wait_temperature"] for step in steps if "wait_temperature" in step]
    assert all(wait["equilibration_s"] == 15.0 for wait in waits)
    assert [
        step["set_temperature"]["setpoint_K"] for step in steps if "set_temperature" in step
    ] == [6.0, 4.0, 2.0]


def test_composable_yaml_round_trip_restores_high_level_blocks():
    blocks = [
        CommentBlock("Combined transport run"),
        SetFieldBlock(0.0, 0.1),
        WaitFieldBlock(600.0),
        RhoVsTemperatureContinuousBlock(
            start_K=300.0,
            stop_K=2.0,
            rate_K_per_min=2.0,
            timeout_s=20_000.0,
        ),
    ]
    sequence = blocks_to_sequence(blocks, SAFETY)

    loaded = parse_sequence(yaml.safe_load(yaml.safe_dump(sequence, sort_keys=False)))

    assert blocks_from_sequence(loaded) == blocks
    assert loaded["metadata"]["composable_schema"] == 1
    assert any("measure_until" in step for step in loaded["steps"])


def test_manual_yaml_import_preserves_equilibration_in_custom_wait():
    manual = {
        "version": 1,
        "steps": [
            {
                "name": "Legacy combined temperature command",
                "set_temperature": {
                    "setpoint_K": 10.0,
                    "rate_K_per_min": 2.0,
                    "wait": True,
                    "timeout_s": 600.0,
                    "settle_s": 300.0,
                },
            }
        ],
    }

    imported = blocks_from_sequence(manual)

    assert [block.KIND for block in imported] == [
        "set_temperature",
        "wait_temperature",
    ]
    assert imported[1].equilibration_s == 300.0


def test_multiple_measurement_routines_compose_in_one_experiment():
    blocks = [
        SetFieldBlock(0.0, 0.1),
        WaitFieldBlock(600.0),
        RhoVsTemperatureContinuousBlock(
            start_K=300.0,
            stop_K=2.0,
            rate_K_per_min=2.0,
            timeout_s=20_000.0,
        ),
        SetTemperatureBlock(10.0, 2.0),
        WaitTemperatureBlock(600.0),
        TemperatureEquilibrationBlock(120.0),
        RhoVsFieldContinuousBlock(
            start_T=-9.0,
            stop_T=9.0,
            rate_T_per_min=0.1,
            timeout_s=20_000.0,
        ),
        SetFieldBlock(0.0, 0.1),
        WaitFieldBlock(600.0),
        FieldEquilibrationBlock(30.0),
    ]

    sequence = blocks_to_sequence(blocks, SAFETY)
    quantities = [
        step["measure_until"]["quantity"] for step in sequence["steps"] if "measure_until" in step
    ]

    assert quantities == ["temperature", "field"]
    assert sequence["steps"][-1]["delay"]["duration_s"] == 30.0


class _MemoryDataFile:
    @property
    def is_open(self):
        return True

    def write_record(self, _record):
        pass


def test_delay_step_is_cooperatively_abortable():
    abort = threading.Event()
    pause = threading.Event()
    lakeshore = MockLakeShore372Controller()
    ppms = MockPPMSController(safety=SAFETY)
    lakeshore.connect()
    ppms.connect()
    engine = ResistivityMeasurementEngine(
        lakeshore,
        ppms,
        _MemoryDataFile(),
        SampleGeometry(),
        abort,
        pause,
    )
    runner = SequenceRunner(ppms, lakeshore, engine, SAFETY, abort, pause)
    sequence = blocks_to_sequence([DelayBlock(10.0)], SAFETY)
    thread = threading.Thread(target=runner.run, args=(sequence,))

    thread.start()
    time.sleep(0.04)
    abort.set()
    thread.join(timeout=1.0)

    assert not thread.is_alive()


def _operation(step):
    return next(key for key in step if key != "name")
