import pytest

from resistivity372.core.exceptions import SequenceValidationError
from resistivity372.core.safety import SafetyLimits
from resistivity372.measurement.sequence import expanded_steps, loop_values, parse_sequence
from resistivity372.measurement.sequence_runner import validate_sequence_against_safety


def test_loop_values_positive():
    values = loop_values({"start": -1, "stop": 1, "step": 1})
    assert values == [-1.0, 0.0, 1.0]


def test_loop_values_negative():
    values = loop_values({"start": 1, "stop": -1, "step": -1})
    assert values == [1.0, 0.0, -1.0]


def test_loop_zero_step_rejected():
    with pytest.raises(SequenceValidationError):
        loop_values({"start": 0, "stop": 1, "step": 0})


def test_expand_substitutes_numeric_values():
    steps = [
        {
            "loop": {
                "variable": "field_T",
                "values": [-1, 0, 1],
                "steps": [
                    {"set_field": {"setpoint_T": "${field_T}", "rate_T_per_min": 0.1}},
                ],
            }
        }
    ]
    out = list(expanded_steps(steps))
    assert [s["set_field"]["setpoint_T"] for s in out] == [-1.0, 0.0, 1.0]


def test_parse_sequence_rejects_non_mapping_yaml():
    with pytest.raises(SequenceValidationError):
        parse_sequence(["not", "a", "mapping"])


def test_validation_reports_malformed_measure_step():
    sequence = {"version": 1, "steps": [{"measure": {"channel": 1}}]}
    with pytest.raises(SequenceValidationError, match="points or duration"):
        validate_sequence_against_safety(sequence, SafetyLimits())


def test_validation_rejects_nonpositive_measurement_interval():
    sequence = {
        "version": 1,
        "steps": [{"measure": {"channel": 1, "points": 2, "interval_s": 0}}],
    }
    with pytest.raises(SequenceValidationError, match="interval_s"):
        validate_sequence_against_safety(sequence, SafetyLimits())
