from __future__ import annotations

import logging
import threading
import time
from typing import Any

from resistivity372.core.exceptions import SequenceValidationError
from resistivity372.core.safety import SafetyLimits
from resistivity372.instruments.lakeshore372 import LakeShore372Interface
from resistivity372.instruments.ppms_multipyvu import PPMSInterface
from resistivity372.measurement.engine import ResistivityMeasurementEngine
from resistivity372.measurement.sequence import expanded_steps

log = logging.getLogger(__name__)


class SequenceRunner:
    def __init__(
        self,
        ppms: PPMSInterface,
        lakeshore: LakeShore372Interface,
        engine: ResistivityMeasurementEngine,
        safety: SafetyLimits,
        abort_flag: threading.Event,
        pause_flag: threading.Event,
        dry_run: bool = False,
        on_step=None,
        on_log=None,
    ):
        self.ppms = ppms
        self.lakeshore = lakeshore
        self.engine = engine
        self.safety = safety
        self.abort_flag = abort_flag
        self.pause_flag = pause_flag
        self.dry_run = dry_run
        self.on_step = on_step or (lambda index, name: None)
        self.on_log = on_log or (lambda msg: None)
        self._run_t0 = time.monotonic()

    def validate(self, sequence: dict[str, Any]) -> None:
        validate_sequence_against_safety(sequence, self.safety)

    def run(self, sequence: dict[str, Any]) -> None:
        self.validate(sequence)
        for index, step in enumerate(expanded_steps(sequence["steps"])):
            if self.abort_flag.is_set():
                break
            self._pause_if_requested()
            step_name = str(step.get("name") or next(iter(step.keys())))
            self.on_step(index, step_name)
            self.on_log(f"Starting step {index}: {step_name}")
            self._execute_step(index, step, step_name)

    def _execute_step(self, index: int, step: dict[str, Any], step_name: str) -> None:
        if "comment" in step:
            self.on_log(str(step["comment"]))
            return

        if "delay" in step:
            duration_s = float(step["delay"]["duration_s"])
            self.on_log(f"Delay: {duration_s:g} s")
            self._delay(duration_s)
            return

        if "set_temperature" in step:
            cfg = step["set_temperature"]
            self.on_log(
                f"Temperature command: {cfg['setpoint_K']} K at {cfg['rate_K_per_min']} K/min"
            )
            self.ppms.set_temperature(
                setpoint_K=float(cfg["setpoint_K"]),
                rate_K_per_min=float(cfg["rate_K_per_min"]),
                approach=str(cfg.get("approach", "fast_settle")),
            )
            if cfg.get("wait", False):
                self.on_log("Waiting for PPMS temperature stability.")
                self.ppms.wait_until_steady(
                    targets=("temperature",),
                    timeout_s=float(cfg.get("timeout_s", 3600)),
                    settle_s=float(cfg.get("settle_s", 0)),
                    abort_flag=self.abort_flag,
                )
            return

        if "wait_temperature" in step:
            cfg = step["wait_temperature"]
            self.on_log("Waiting for PPMS temperature stability.")
            self.ppms.wait_until_steady(
                targets=("temperature",),
                timeout_s=float(cfg.get("timeout_s", 3600)),
                settle_s=float(cfg.get("settle_s", 0)),
                abort_flag=self.abort_flag,
            )
            return

        if "set_field" in step:
            cfg = step["set_field"]
            self.on_log(
                f"Field command: {cfg['setpoint_T']} T at {cfg['rate_T_per_min']} T/min"
            )
            self.ppms.set_field(
                setpoint_T=float(cfg["setpoint_T"]),
                rate_T_per_min=float(cfg["rate_T_per_min"]),
                approach=str(cfg.get("approach", "linear")),
                driven_mode=cfg.get("driven_mode"),
            )
            if cfg.get("wait", False):
                self.on_log("Waiting for PPMS field stability.")
                self.ppms.wait_until_steady(
                    targets=("field",),
                    timeout_s=float(cfg.get("timeout_s", 3600)),
                    settle_s=float(cfg.get("settle_s", 0)),
                    abort_flag=self.abort_flag,
                )
            return

        if "wait_field" in step:
            cfg = step["wait_field"]
            self.on_log("Waiting for PPMS field stability.")
            self.ppms.wait_until_steady(
                targets=("field",),
                timeout_s=float(cfg.get("timeout_s", 3600)),
                settle_s=float(cfg.get("settle_s", 0)),
                abort_flag=self.abort_flag,
            )
            return

        if "set_chamber" in step:
            cfg = step["set_chamber"]
            self.on_log(f"Chamber command: {cfg['mode']}")
            self.ppms.set_chamber(str(cfg["mode"]))
            if cfg.get("wait", False):
                self.ppms.wait_until_steady(
                    targets=("chamber",),
                    timeout_s=float(cfg.get("timeout_s", 1800)),
                    settle_s=float(cfg.get("settle_s", 0)),
                    abort_flag=self.abort_flag,
                )
            return

        if "set_position" in step:
            cfg = step["set_position"]
            self.on_log(
                f"Position command: {cfg['position_deg']} deg at "
                f"{cfg.get('rate_deg_per_s', 1.0)} deg/s"
            )
            self.ppms.set_position(
                position_deg=float(cfg["position_deg"]),
                rate_deg_per_s=float(cfg.get("rate_deg_per_s", 1.0)),
            )
            return

        if "measure" in step:
            cfg = step["measure"]
            self.on_log(
                f"Measurement acquisition: channel={cfg.get('channel', 1)} "
                f"points={cfg.get('points')} duration_s={cfg.get('duration_s')}"
            )
            self.engine.measure(
                channel=cfg.get("channel", 1),
                interval_s=float(cfg.get("interval_s", 1.0)),
                points=cfg.get("points"),
                duration_s=cfg.get("duration_s"),
                step_index=index,
                step_name=str(cfg.get("name", step_name)),
                start_time=self._run_t0,
            )
            return

        if "measure_until" in step:
            cfg = step["measure_until"]
            self.on_log(
                f"Continuous acquisition: channel={cfg.get('channel', 1)} "
                f"until {cfg['quantity']}={cfg['target']} +/- {cfg['tolerance']}"
            )
            self.engine.measure_until(
                channel=cfg.get("channel", 1),
                interval_s=float(cfg.get("interval_s", 1.0)),
                quantity=str(cfg["quantity"]),
                target=float(cfg["target"]),
                tolerance=float(cfg["tolerance"]),
                timeout_s=float(cfg["timeout_s"]),
                require_stable=bool(cfg.get("require_stable", True)),
                settle_s=float(cfg.get("settle_s", 0.0)),
                step_index=index,
                step_name=str(cfg.get("name", step_name)),
                start_time=self._run_t0,
            )
            return

        raise SequenceValidationError(f"Unknown step: {step}")

    def _validate_step(self, step: dict[str, Any]) -> None:
        _validate_expanded_step(step, self.safety)

    def _pause_if_requested(self) -> None:
        while self.pause_flag.is_set() and not self.abort_flag.is_set():
            time.sleep(0.05)

    def _delay(self, duration_s: float) -> None:
        deadline = time.monotonic() + duration_s
        while not self.abort_flag.is_set() and time.monotonic() < deadline:
            if self.pause_flag.is_set():
                paused_at = time.monotonic()
                self._pause_if_requested()
                deadline += time.monotonic() - paused_at
                continue
            time.sleep(max(0.0, min(0.05, deadline - time.monotonic())))


def validate_sequence_against_safety(sequence: dict[str, Any], safety: SafetyLimits) -> None:
    """Validate sequence syntax and safety limits without connecting instruments or opening files."""
    if sequence.get("version") != 1:
        raise SequenceValidationError("Only sequence version 1 is supported.")
    steps = sequence.get("steps")
    if not isinstance(steps, list) or not steps:
        raise SequenceValidationError("Sequence must contain a non-empty steps list.")

    recognized = {
        "comment",
        "delay",
        "set_temperature",
        "wait_temperature",
        "set_field",
        "wait_field",
        "set_chamber",
        "set_position",
        "measure",
        "measure_until",
    }

    for index, step in enumerate(expanded_steps(steps)):
        try:
            _validate_expanded_step(step, safety, recognized)
        except SequenceValidationError as exc:
            raise SequenceValidationError(f"Invalid expanded step {index}: {exc}") from exc
        except (KeyError, TypeError, ValueError) as exc:
            raise SequenceValidationError(f"Invalid expanded step {index}: {exc}") from exc


def _validate_expanded_step(
    step: dict[str, Any],
    safety: SafetyLimits,
    recognized: set[str] | None = None,
) -> None:
    recognized = recognized or {
        "comment",
        "delay",
        "set_temperature",
        "wait_temperature",
        "set_field",
        "wait_field",
        "set_chamber",
        "set_position",
        "measure",
        "measure_until",
    }
    operations = [key for key in recognized if key in step]
    if not operations:
        raise SequenceValidationError(f"Unknown sequence step: {step}")
    if len(operations) > 1:
        raise SequenceValidationError(
            f"A step must contain one operation, found: {', '.join(sorted(operations))}."
        )

    if "delay" in step:
        cfg = _mapping_config(step, "delay")
        if float(cfg["duration_s"]) <= 0:
            raise SequenceValidationError("delay duration_s must be positive.")

    if "set_temperature" in step:
        cfg = _mapping_config(step, "set_temperature")
        safety.check_temperature(float(cfg["setpoint_K"]), float(cfg["rate_K_per_min"]))
        _validate_wait_options(cfg, "set_temperature")
    if "wait_temperature" in step:
        _validate_wait_options(_mapping_config(step, "wait_temperature"), "wait_temperature")
    if "set_field" in step:
        cfg = _mapping_config(step, "set_field")
        safety.check_field(float(cfg["setpoint_T"]), float(cfg["rate_T_per_min"]))
        _validate_wait_options(cfg, "set_field")
    if "wait_field" in step:
        _validate_wait_options(_mapping_config(step, "wait_field"), "wait_field")
    if "set_chamber" in step:
        cfg = _mapping_config(step, "set_chamber")
        safety.check_chamber(str(cfg["mode"]))
        _validate_wait_options(cfg, "set_chamber")
    if "set_position" in step:
        cfg = _mapping_config(step, "set_position")
        safety.check_position(float(cfg["position_deg"]), float(cfg.get("rate_deg_per_s", 1.0)))
    if "measure" in step:
        cfg = _mapping_config(step, "measure")
        if "points" not in cfg and "duration_s" not in cfg:
            raise SequenceValidationError("measure step requires points or duration_s.")
        if float(cfg.get("interval_s", 1.0)) <= 0:
            raise SequenceValidationError("measure interval_s must be positive.")
        if cfg.get("points") is not None and int(cfg["points"]) <= 0:
            raise SequenceValidationError("measure points must be positive.")
        if cfg.get("duration_s") is not None and float(cfg["duration_s"]) <= 0:
            raise SequenceValidationError("measure duration_s must be positive.")
    if "measure_until" in step:
        cfg = _mapping_config(step, "measure_until")
        quantity = str(cfg["quantity"])
        target = float(cfg["target"])
        if quantity == "temperature":
            safety.check_temperature(target, 0.0)
        elif quantity == "field":
            safety.check_field(target, 0.0)
        else:
            raise SequenceValidationError(
                "measure_until quantity must be 'temperature' or 'field'."
            )
        if float(cfg.get("interval_s", 1.0)) <= 0:
            raise SequenceValidationError("measure_until interval_s must be positive.")
        if float(cfg["tolerance"]) <= 0:
            raise SequenceValidationError("measure_until tolerance must be positive.")
        if float(cfg["timeout_s"]) <= 0:
            raise SequenceValidationError("measure_until timeout_s must be positive.")
        if float(cfg.get("settle_s", 0.0)) < 0:
            raise SequenceValidationError("measure_until settle_s cannot be negative.")


def _mapping_config(step: dict[str, Any], operation: str) -> dict[str, Any]:
    config = step[operation]
    if not isinstance(config, dict):
        raise SequenceValidationError(f"{operation} must contain a mapping.")
    return config


def _validate_wait_options(config: dict[str, Any], operation: str) -> None:
    if "timeout_s" in config and float(config["timeout_s"]) <= 0:
        raise SequenceValidationError(f"{operation} timeout_s must be positive.")
    if "settle_s" in config and float(config["settle_s"]) < 0:
        raise SequenceValidationError(f"{operation} settle_s cannot be negative.")
