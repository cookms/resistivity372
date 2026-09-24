from __future__ import annotations

import math
from typing import Any

from resistivity372.core.exceptions import SequenceValidationError
from resistivity372.core.safety import SafetyLimits
from resistivity372.measurement.sequence_runner import validate_sequence_against_safety

EXPERIMENT_STEPPED_T = "rho_vs_t_stepped"
EXPERIMENT_CONTINUOUS_T = "rho_vs_t_continuous"
EXPERIMENT_STEPPED_H = "rho_vs_h_stepped"
EXPERIMENT_CONTINUOUS_H = "rho_vs_h_continuous"


def parse_number_list(text: str) -> list[float]:
    values = []
    for part in text.split(","):
        stripped = part.strip()
        if not stripped:
            continue
        try:
            values.append(float(stripped))
        except ValueError as exc:
            raise SequenceValidationError(
                f"Expected a comma-separated numeric list, but {stripped!r} is not numeric."
            ) from exc
    if not values:
        raise SequenceValidationError("Enter at least one magnetic-field value.")
    return values


def inclusive_setpoints(start: float, stop: float, step: float) -> list[float]:
    """Return direction-aware setpoints, including the stop when it lies on the grid."""
    start = float(start)
    stop = float(stop)
    magnitude = abs(float(step))
    if not math.isfinite(start) or not math.isfinite(stop) or not math.isfinite(magnitude):
        raise SequenceValidationError("Sweep start, stop, and step must be finite numbers.")
    if magnitude == 0:
        raise SequenceValidationError("Sweep step must be positive.")
    if math.isclose(start, stop, rel_tol=0.0, abs_tol=1e-12):
        return [start]

    direction = 1.0 if stop > start else -1.0
    signed_step = direction * magnitude
    count = int(math.floor(abs(stop - start) / magnitude + 1e-12))
    values = [round(start + index * signed_step, 12) for index in range(count + 1)]
    if math.isclose(values[-1], stop, rel_tol=1e-10, abs_tol=magnitude * 1e-10):
        values[-1] = stop
    return values


def build_stepped_temperature_sequence(
    *,
    safety: SafetyLimits,
    field_values_T: list[float],
    field_rate_T_per_min: float,
    temperature_start_K: float,
    temperature_stop_K: float,
    temperature_step_K: float,
    temperature_rate_K_per_min: float,
    equilibration_s: float,
    channel: int | str,
    interval_s: float,
    points: int | None,
    duration_s: float | None,
    timeout_s: float,
) -> dict[str, Any]:
    temperatures = inclusive_setpoints(temperature_start_K, temperature_stop_K, temperature_step_K)
    acquisition = _measurement_config(channel, interval_s, points, duration_s)
    steps: list[dict[str, Any]] = [
        {"name": "Generated transport sequence", "comment": "rho vs T - stepped temperature"}
    ]
    for field_T in _require_fields(field_values_T):
        steps.append(
            {
                "name": f"Set field {field_T:g} T",
                "set_field": _field_command(field_T, field_rate_T_per_min, True, timeout_s, 0.0),
            }
        )
        for temperature_K in temperatures:
            steps.append(
                {
                    "name": f"Set temperature {temperature_K:g} K",
                    "set_temperature": _temperature_command(
                        temperature_K,
                        temperature_rate_K_per_min,
                        True,
                        timeout_s,
                        equilibration_s,
                    ),
                }
            )
            measure = dict(acquisition)
            measure["name"] = f"rho(T) B={field_T:g} T, T={temperature_K:g} K"
            steps.append({"name": measure["name"], "measure": measure})
    return _finish_sequence(EXPERIMENT_STEPPED_T, steps, safety)


def build_continuous_temperature_sequence(
    *,
    safety: SafetyLimits,
    field_values_T: list[float],
    field_rate_T_per_min: float,
    temperature_start_K: float,
    temperature_stop_K: float,
    temperature_rate_K_per_min: float,
    initial_equilibration_s: float,
    channel: int | str,
    interval_s: float,
    target_tolerance_K: float,
    target_settle_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    if math.isclose(temperature_start_K, temperature_stop_K):
        raise SequenceValidationError("Continuous temperature start and stop must differ.")
    steps: list[dict[str, Any]] = [
        {"name": "Generated transport sequence", "comment": "rho vs T - continuous sweep"}
    ]
    for field_T in _require_fields(field_values_T):
        steps.extend(
            [
                {
                    "name": f"Set field {field_T:g} T",
                    "set_field": _field_command(
                        field_T,
                        field_rate_T_per_min,
                        True,
                        timeout_s,
                        0.0,
                    ),
                },
                {
                    "name": f"Stabilize at {temperature_start_K:g} K",
                    "set_temperature": _temperature_command(
                        temperature_start_K,
                        temperature_rate_K_per_min,
                        True,
                        timeout_s,
                        initial_equilibration_s,
                    ),
                },
                {
                    "name": f"Ramp temperature to {temperature_stop_K:g} K",
                    "set_temperature": _temperature_command(
                        temperature_stop_K,
                        temperature_rate_K_per_min,
                        False,
                        timeout_s,
                        0.0,
                    ),
                },
                {
                    "name": f"Acquire rho(T) at {field_T:g} T",
                    "measure_until": _measure_until_config(
                        channel=channel,
                        interval_s=interval_s,
                        quantity="temperature",
                        target=temperature_stop_K,
                        tolerance=target_tolerance_K,
                        settle_s=0.0,
                        timeout_s=timeout_s,
                    ),
                },
                {
                    "name": f"Confirm temperature stable at {temperature_stop_K:g} K",
                    "wait_temperature": {
                        "target_K": float(temperature_stop_K),
                        "tolerance_K": float(target_tolerance_K),
                        "stable_s": float(target_settle_s),
                        "equilibration_s": 0.0,
                        "timeout_s": float(timeout_s),
                    },
                },
            ]
        )
    return _finish_sequence(EXPERIMENT_CONTINUOUS_T, steps, safety)


def build_stepped_field_sequence(
    *,
    safety: SafetyLimits,
    fixed_temperature_K: float,
    temperature_rate_K_per_min: float,
    field_start_T: float,
    field_stop_T: float,
    field_step_T: float,
    field_rate_T_per_min: float,
    equilibration_s: float,
    channel: int | str,
    interval_s: float,
    points: int | None,
    duration_s: float | None,
    timeout_s: float,
) -> dict[str, Any]:
    fields = inclusive_setpoints(field_start_T, field_stop_T, field_step_T)
    acquisition = _measurement_config(channel, interval_s, points, duration_s)
    steps: list[dict[str, Any]] = [
        {"name": "Generated transport sequence", "comment": "rho vs H - stepped field"},
        {
            "name": f"Stabilize at {fixed_temperature_K:g} K",
            "set_temperature": _temperature_command(
                fixed_temperature_K,
                temperature_rate_K_per_min,
                True,
                timeout_s,
                0.0,
            ),
        },
    ]
    for field_T in fields:
        steps.append(
            {
                "name": f"Set field {field_T:g} T",
                "set_field": _field_command(
                    field_T, field_rate_T_per_min, True, timeout_s, equilibration_s
                ),
            }
        )
        measure = dict(acquisition)
        measure["name"] = f"rho(H) T={fixed_temperature_K:g} K, B={field_T:g} T"
        steps.append({"name": measure["name"], "measure": measure})
    return _finish_sequence(EXPERIMENT_STEPPED_H, steps, safety)


def build_continuous_field_sequence(
    *,
    safety: SafetyLimits,
    fixed_temperature_K: float,
    temperature_rate_K_per_min: float,
    field_start_T: float,
    field_stop_T: float,
    field_rate_T_per_min: float,
    initial_equilibration_s: float,
    channel: int | str,
    interval_s: float,
    target_tolerance_T: float,
    target_settle_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    if math.isclose(field_start_T, field_stop_T):
        raise SequenceValidationError("Continuous field start and stop must differ.")
    steps: list[dict[str, Any]] = [
        {"name": "Generated transport sequence", "comment": "rho vs H - continuous sweep"},
        {
            "name": f"Stabilize at {fixed_temperature_K:g} K",
            "set_temperature": _temperature_command(
                fixed_temperature_K,
                temperature_rate_K_per_min,
                True,
                timeout_s,
                0.0,
            ),
        },
        {
            "name": f"Stabilize field at {field_start_T:g} T",
            "set_field": _field_command(
                field_start_T,
                field_rate_T_per_min,
                True,
                timeout_s,
                initial_equilibration_s,
            ),
        },
        {
            "name": f"Sweep field to {field_stop_T:g} T",
            "set_field": _field_command(field_stop_T, field_rate_T_per_min, False, timeout_s, 0.0),
        },
        {
            "name": f"Acquire rho(H) at {fixed_temperature_K:g} K",
            "measure_until": _measure_until_config(
                channel=channel,
                interval_s=interval_s,
                quantity="field",
                target=field_stop_T,
                tolerance=target_tolerance_T,
                settle_s=0.0,
                timeout_s=timeout_s,
            ),
        },
        {
            "name": f"Confirm field stable at {field_stop_T:g} T",
            "wait_field": {
                "target_T": float(field_stop_T),
                "tolerance_T": float(target_tolerance_T),
                "stable_s": float(target_settle_s),
                "equilibration_s": 0.0,
                "read_delay_s": 10.0,
                "timeout_s": float(timeout_s),
            },
        },
    ]
    return _finish_sequence(EXPERIMENT_CONTINUOUS_H, steps, safety)


def _measurement_config(
    channel: int | str,
    interval_s: float,
    points: int | None,
    duration_s: float | None,
) -> dict[str, Any]:
    config: dict[str, Any] = {"channel": channel, "interval_s": float(interval_s)}
    if points is not None:
        config["points"] = int(points)
    if duration_s is not None:
        config["duration_s"] = float(duration_s)
    if points is None and duration_s is None:
        raise SequenceValidationError(
            "Stepped acquisition requires points per setpoint and/or measurement duration."
        )
    return config


def _temperature_command(
    target: float,
    rate: float,
    wait: bool,
    timeout_s: float,
    settle_s: float,
) -> dict[str, Any]:
    return {
        "setpoint_K": float(target),
        "rate_K_per_min": float(rate),
        "approach": "fast_settle",
        "wait": bool(wait),
        "timeout_s": float(timeout_s),
        "tolerance_K": 0.05,
        "stable_s": 0.0,
        "equilibration_s": float(settle_s),
    }


def _field_command(
    target: float,
    rate: float,
    wait: bool,
    timeout_s: float,
    settle_s: float,
) -> dict[str, Any]:
    return {
        "setpoint_T": float(target),
        "rate_T_per_min": float(rate),
        "approach": "linear",
        "wait": bool(wait),
        "timeout_s": float(timeout_s),
        "tolerance_T": 0.001,
        "stable_s": 0.0,
        "equilibration_s": float(settle_s),
        "read_delay_s": 10.0,
    }


def _measure_until_config(
    *,
    channel: int | str,
    interval_s: float,
    quantity: str,
    target: float,
    tolerance: float,
    settle_s: float,
    timeout_s: float,
) -> dict[str, Any]:
    return {
        "channel": channel,
        "interval_s": float(interval_s),
        "quantity": quantity,
        "target": float(target),
        "tolerance": float(tolerance),
        "require_stable": False,
        "settle_s": float(settle_s),
        "timeout_s": float(timeout_s),
    }


def _require_fields(values: list[float]) -> list[float]:
    if not values:
        raise SequenceValidationError("At least one fixed magnetic-field value is required.")
    return [float(value) for value in values]


def _finish_sequence(
    experiment_type: str,
    steps: list[dict[str, Any]],
    safety: SafetyLimits,
) -> dict[str, Any]:
    sequence = {
        "version": 1,
        "metadata": {
            "generated_by": "resistivity372 transport sequence builder",
            "experiment_type": experiment_type,
        },
        "steps": steps,
    }
    validate_sequence_against_safety(sequence, safety)
    return sequence
