from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Any, ClassVar

from resistivity372.app.sequence_builder import inclusive_setpoints
from resistivity372.core.exceptions import SequenceValidationError
from resistivity372.core.safety import SafetyLimits
from resistivity372.measurement.sequence_runner import validate_sequence_against_safety


@dataclass
class SequenceBlock:
    KIND: ClassVar[str] = "block"
    LABEL: ClassVar[str] = "Block"

    def expand(self) -> list[dict[str, Any]]:
        raise NotImplementedError

    def summary(self) -> str:
        return self.LABEL

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.KIND, **asdict(self)}


@dataclass
class SetTemperatureBlock(SequenceBlock):
    KIND: ClassVar[str] = "set_temperature"
    LABEL: ClassVar[str] = "Set Temperature"
    setpoint_K: float = 10.0
    rate_K_per_min: float = 2.0

    def expand(self) -> list[dict[str, Any]]:
        return [_set_temperature(self.setpoint_K, self.rate_K_per_min)]

    def summary(self) -> str:
        return f"{self.LABEL} — {self.setpoint_K:g} K @ {self.rate_K_per_min:g} K/min"


@dataclass
class WaitTemperatureBlock(SequenceBlock):
    KIND: ClassVar[str] = "wait_temperature"
    LABEL: ClassVar[str] = "Wait for Temperature Stable"
    timeout_s: float = 3600.0

    def expand(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "Wait for temperature stable",
                "wait_temperature": {"timeout_s": float(self.timeout_s), "settle_s": 0.0},
            }
        ]

    def summary(self) -> str:
        return f"{self.LABEL} — timeout {self.timeout_s:g} s"


@dataclass
class TemperatureEquilibrationBlock(SequenceBlock):
    KIND: ClassVar[str] = "temperature_equilibration"
    LABEL: ClassVar[str] = "Equilibrate at Temperature"
    duration_s: float = 300.0

    def expand(self) -> list[dict[str, Any]]:
        return [_delay(self.duration_s, "Equilibrate after temperature stable")]

    def summary(self) -> str:
        return f"{self.LABEL} — {self.duration_s:g} s after stable"


@dataclass
class SetFieldBlock(SequenceBlock):
    KIND: ClassVar[str] = "set_field"
    LABEL: ClassVar[str] = "Set Field"
    setpoint_T: float = 0.0
    rate_T_per_min: float = 0.1

    def expand(self) -> list[dict[str, Any]]:
        return [_set_field(self.setpoint_T, self.rate_T_per_min)]

    def summary(self) -> str:
        return f"{self.LABEL} — {self.setpoint_T:g} T @ {self.rate_T_per_min:g} T/min"


@dataclass
class WaitFieldBlock(SequenceBlock):
    KIND: ClassVar[str] = "wait_field"
    LABEL: ClassVar[str] = "Wait for Field Stable"
    timeout_s: float = 3600.0

    def expand(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "Wait for field stable",
                "wait_field": {"timeout_s": float(self.timeout_s), "settle_s": 0.0},
            }
        ]

    def summary(self) -> str:
        return f"{self.LABEL} — timeout {self.timeout_s:g} s"


@dataclass
class FieldEquilibrationBlock(SequenceBlock):
    KIND: ClassVar[str] = "field_equilibration"
    LABEL: ClassVar[str] = "Equilibrate at Field"
    duration_s: float = 120.0

    def expand(self) -> list[dict[str, Any]]:
        return [_delay(self.duration_s, "Equilibrate after field stable")]

    def summary(self) -> str:
        return f"{self.LABEL} — {self.duration_s:g} s after stable"


@dataclass
class DelayBlock(SequenceBlock):
    KIND: ClassVar[str] = "delay"
    LABEL: ClassVar[str] = "Delay / Wait"
    duration_s: float = 60.0

    def expand(self) -> list[dict[str, Any]]:
        return [_delay(self.duration_s, "Delay")]

    def summary(self) -> str:
        return f"{self.LABEL} — {self.duration_s:g} s"


@dataclass
class CommentBlock(SequenceBlock):
    KIND: ClassVar[str] = "comment"
    LABEL: ClassVar[str] = "Comment / Marker"
    text: str = "Operator marker"

    def expand(self) -> list[dict[str, Any]]:
        if not self.text.strip():
            raise SequenceValidationError("Comment text cannot be empty.")
        return [{"name": self.text.strip(), "comment": self.text.strip()}]

    def summary(self) -> str:
        return f"{self.LABEL} — {self.text.strip() or '(empty)'}"


@dataclass
class MeasureBlock(SequenceBlock):
    KIND: ClassVar[str] = "measure"
    LABEL: ClassVar[str] = "Measure Resistance"
    channel: int = 1
    interval_s: float = 1.0
    points: int | None = 20
    duration_s: float | None = None

    def expand(self) -> list[dict[str, Any]]:
        return [_measure(self.channel, self.interval_s, self.points, self.duration_s, self.LABEL)]

    def summary(self) -> str:
        limits = []
        if self.points is not None:
            limits.append(f"{self.points} points")
        if self.duration_s is not None:
            limits.append(f"{self.duration_s:g} s")
        return f"{self.LABEL} — {', '.join(limits) or 'no stop condition'}, every {self.interval_s:g} s"


@dataclass
class RhoVsTemperatureSteppedBlock(SequenceBlock):
    KIND: ClassVar[str] = "rho_t_stepped"
    LABEL: ClassVar[str] = "rho vs T — Stepped"
    start_K: float = 2.0
    stop_K: float = 10.0
    step_K: float = 2.0
    rate_K_per_min: float = 2.0
    equilibration_s: float = 0.0
    timeout_s: float = 7200.0
    channel: int = 1
    interval_s: float = 1.0
    points: int | None = 5
    duration_s: float | None = None

    def expand(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for target in inclusive_setpoints(self.start_K, self.stop_K, self.step_K):
            steps.append(_set_temperature(target, self.rate_K_per_min))
            steps.extend(WaitTemperatureBlock(self.timeout_s).expand())
            if self.equilibration_s > 0:
                steps.extend(TemperatureEquilibrationBlock(self.equilibration_s).expand())
            steps.append(
                _measure(
                    self.channel,
                    self.interval_s,
                    self.points,
                    self.duration_s,
                    f"rho(T) at {target:g} K",
                )
            )
        return steps

    def summary(self) -> str:
        return (
            f"{self.LABEL} — {self.start_K:g} → {self.stop_K:g} K, "
            f"step {abs(self.step_K):g} K @ {self.rate_K_per_min:g} K/min"
        )


@dataclass
class RhoVsTemperatureContinuousBlock(SequenceBlock):
    KIND: ClassVar[str] = "rho_t_continuous"
    LABEL: ClassVar[str] = "rho vs T — Continuous"
    start_K: float = 300.0
    stop_K: float = 2.0
    rate_K_per_min: float = 2.0
    initial_equilibration_s: float = 0.0
    channel: int = 1
    interval_s: float = 1.0
    tolerance_K: float = 0.05
    stable_at_target_s: float = 0.0
    timeout_s: float = 20_000.0

    def expand(self) -> list[dict[str, Any]]:
        if self.start_K == self.stop_K:
            raise SequenceValidationError("Continuous temperature start and stop must differ.")
        steps = [_set_temperature(self.start_K, self.rate_K_per_min)]
        steps.extend(WaitTemperatureBlock(self.timeout_s).expand())
        if self.initial_equilibration_s > 0:
            steps.extend(TemperatureEquilibrationBlock(self.initial_equilibration_s).expand())
        steps.append(_set_temperature(self.stop_K, self.rate_K_per_min))
        steps.append(
            _measure_until(
                self.channel,
                self.interval_s,
                "temperature",
                self.stop_K,
                self.tolerance_K,
                self.stable_at_target_s,
                self.timeout_s,
                f"rho(T) {self.start_K:g} to {self.stop_K:g} K",
            )
        )
        return steps

    def summary(self) -> str:
        return (
            f"{self.LABEL} — {self.start_K:g} → {self.stop_K:g} K "
            f"@ {self.rate_K_per_min:g} K/min"
        )


@dataclass
class RhoVsFieldSteppedBlock(SequenceBlock):
    KIND: ClassVar[str] = "rho_h_stepped"
    LABEL: ClassVar[str] = "rho vs H — Stepped"
    start_T: float = -1.0
    stop_T: float = 1.0
    step_T: float = 0.1
    rate_T_per_min: float = 0.1
    equilibration_s: float = 0.0
    timeout_s: float = 7200.0
    channel: int = 1
    interval_s: float = 1.0
    points: int | None = 5
    duration_s: float | None = None

    def expand(self) -> list[dict[str, Any]]:
        steps: list[dict[str, Any]] = []
        for target in inclusive_setpoints(self.start_T, self.stop_T, self.step_T):
            steps.append(_set_field(target, self.rate_T_per_min))
            steps.extend(WaitFieldBlock(self.timeout_s).expand())
            if self.equilibration_s > 0:
                steps.extend(FieldEquilibrationBlock(self.equilibration_s).expand())
            steps.append(
                _measure(
                    self.channel,
                    self.interval_s,
                    self.points,
                    self.duration_s,
                    f"rho(H) at {target:g} T",
                )
            )
        return steps

    def summary(self) -> str:
        return (
            f"{self.LABEL} — {self.start_T:g} → {self.stop_T:g} T, "
            f"step {abs(self.step_T):g} T @ {self.rate_T_per_min:g} T/min"
        )


@dataclass
class RhoVsFieldContinuousBlock(SequenceBlock):
    KIND: ClassVar[str] = "rho_h_continuous"
    LABEL: ClassVar[str] = "rho vs H — Continuous"
    start_T: float = -1.0
    stop_T: float = 1.0
    rate_T_per_min: float = 0.1
    initial_equilibration_s: float = 0.0
    channel: int = 1
    interval_s: float = 1.0
    tolerance_T: float = 0.001
    stable_at_target_s: float = 0.0
    timeout_s: float = 20_000.0

    def expand(self) -> list[dict[str, Any]]:
        if self.start_T == self.stop_T:
            raise SequenceValidationError("Continuous field start and stop must differ.")
        steps = [_set_field(self.start_T, self.rate_T_per_min)]
        steps.extend(WaitFieldBlock(self.timeout_s).expand())
        if self.initial_equilibration_s > 0:
            steps.extend(FieldEquilibrationBlock(self.initial_equilibration_s).expand())
        steps.append(_set_field(self.stop_T, self.rate_T_per_min))
        steps.append(
            _measure_until(
                self.channel,
                self.interval_s,
                "field",
                self.stop_T,
                self.tolerance_T,
                self.stable_at_target_s,
                self.timeout_s,
                f"rho(H) {self.start_T:g} to {self.stop_T:g} T",
            )
        )
        return steps

    def summary(self) -> str:
        return (
            f"{self.LABEL} — {self.start_T:g} → {self.stop_T:g} T "
            f"@ {self.rate_T_per_min:g} T/min"
        )


@dataclass
class RawStepBlock(SequenceBlock):
    KIND: ClassVar[str] = "raw_step"
    LABEL: ClassVar[str] = "Imported YAML Step"
    step: dict[str, Any] | None = None

    def expand(self) -> list[dict[str, Any]]:
        if not isinstance(self.step, dict):
            raise SequenceValidationError("Imported YAML step must be a mapping.")
        return [deepcopy(self.step)]

    def summary(self) -> str:
        step = self.step or {}
        operation = next((key for key in step if key != "name"), "unknown")
        return f"{self.LABEL} — {step.get('name', operation)}"


BLOCK_TYPES: dict[str, type[SequenceBlock]] = {
    block.KIND: block
    for block in (
        SetTemperatureBlock,
        WaitTemperatureBlock,
        TemperatureEquilibrationBlock,
        SetFieldBlock,
        WaitFieldBlock,
        FieldEquilibrationBlock,
        DelayBlock,
        CommentBlock,
        MeasureBlock,
        RhoVsTemperatureSteppedBlock,
        RhoVsTemperatureContinuousBlock,
        RhoVsFieldSteppedBlock,
        RhoVsFieldContinuousBlock,
        RawStepBlock,
    )
}


def block_from_dict(data: dict[str, Any]) -> SequenceBlock:
    if not isinstance(data, dict):
        raise SequenceValidationError("Composable block entries must be mappings.")
    kind = str(data.get("type", ""))
    cls = BLOCK_TYPES.get(kind)
    if cls is None:
        raise SequenceValidationError(f"Unknown composable block type: {kind!r}.")
    values = {key: deepcopy(value) for key, value in data.items() if key != "type"}
    try:
        return cls(**values)
    except TypeError as exc:
        raise SequenceValidationError(f"Invalid {kind} block: {exc}") from exc


def blocks_to_sequence(
    blocks: list[SequenceBlock],
    safety: SafetyLimits,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if not blocks:
        raise SequenceValidationError("Add at least one block to the experiment.")
    steps = [step for block in blocks for step in block.expand()]
    sequence_metadata = dict(metadata or {})
    sequence_metadata.update(
        {
            "generated_by": "resistivity372 composable sequence builder",
            "composable_schema": 1,
            "composable_blocks": [block.to_dict() for block in blocks],
        }
    )
    sequence = {"version": 1, "metadata": sequence_metadata, "steps": steps}
    validate_sequence_against_safety(sequence, safety)
    return sequence


def blocks_from_sequence(sequence: dict[str, Any]) -> list[SequenceBlock]:
    metadata = sequence.get("metadata", {})
    serialized = metadata.get("composable_blocks") if isinstance(metadata, dict) else None
    if isinstance(serialized, list):
        restored = [block_from_dict(item) for item in serialized]
        restored_steps = [step for block in restored for step in block.expand()]
        if restored_steps == sequence.get("steps"):
            return restored

    blocks: list[SequenceBlock] = []
    for step in sequence.get("steps", []):
        blocks.extend(_primitive_blocks_from_step(step))
    return blocks


def rho_vs_temperature(
    block: RhoVsTemperatureSteppedBlock | RhoVsTemperatureContinuousBlock,
) -> list[dict[str, Any]]:
    return block.expand()


def rho_vs_field(
    block: RhoVsFieldSteppedBlock | RhoVsFieldContinuousBlock,
) -> list[dict[str, Any]]:
    return block.expand()


def _primitive_blocks_from_step(step: dict[str, Any]) -> list[SequenceBlock]:
    if "comment" in step:
        return [CommentBlock(str(step["comment"]))]
    if "delay" in step:
        return [DelayBlock(float(step["delay"].get("duration_s", 0.0)))]
    if "set_temperature" in step:
        cfg = step["set_temperature"]
        result: list[SequenceBlock] = [
            SetTemperatureBlock(float(cfg["setpoint_K"]), float(cfg["rate_K_per_min"]))
        ]
        if cfg.get("wait"):
            result.append(WaitTemperatureBlock(float(cfg.get("timeout_s", 3600.0))))
            if float(cfg.get("settle_s", 0.0)) > 0:
                result.append(TemperatureEquilibrationBlock(float(cfg["settle_s"])))
        return result
    if "wait_temperature" in step:
        cfg = step["wait_temperature"]
        result = [WaitTemperatureBlock(float(cfg.get("timeout_s", 3600.0)))]
        if float(cfg.get("settle_s", 0.0)) > 0:
            result.append(TemperatureEquilibrationBlock(float(cfg["settle_s"])))
        return result
    if "set_field" in step:
        cfg = step["set_field"]
        result = [SetFieldBlock(float(cfg["setpoint_T"]), float(cfg["rate_T_per_min"]))]
        if cfg.get("wait"):
            result.append(WaitFieldBlock(float(cfg.get("timeout_s", 3600.0))))
            if float(cfg.get("settle_s", 0.0)) > 0:
                result.append(FieldEquilibrationBlock(float(cfg["settle_s"])))
        return result
    if "wait_field" in step:
        cfg = step["wait_field"]
        result = [WaitFieldBlock(float(cfg.get("timeout_s", 3600.0)))]
        if float(cfg.get("settle_s", 0.0)) > 0:
            result.append(FieldEquilibrationBlock(float(cfg["settle_s"])))
        return result
    if "measure" in step:
        cfg = step["measure"]
        return [
            MeasureBlock(
                channel=int(cfg.get("channel", 1)),
                interval_s=float(cfg.get("interval_s", 1.0)),
                points=int(cfg["points"]) if cfg.get("points") is not None else None,
                duration_s=(
                    float(cfg["duration_s"]) if cfg.get("duration_s") is not None else None
                ),
            )
        ]
    return [RawStepBlock(deepcopy(step))]


def _set_temperature(target: float, rate: float) -> dict[str, Any]:
    return {
        "name": f"Set temperature {target:g} K",
        "set_temperature": {
            "setpoint_K": float(target),
            "rate_K_per_min": float(rate),
            "approach": "fast_settle",
            "wait": False,
        },
    }


def _set_field(target: float, rate: float) -> dict[str, Any]:
    return {
        "name": f"Set field {target:g} T",
        "set_field": {
            "setpoint_T": float(target),
            "rate_T_per_min": float(rate),
            "approach": "linear",
            "wait": False,
        },
    }


def _delay(duration_s: float, name: str) -> dict[str, Any]:
    return {"name": f"{name} for {duration_s:g} s", "delay": {"duration_s": float(duration_s)}}


def _measure(
    channel: int,
    interval_s: float,
    points: int | None,
    duration_s: float | None,
    name: str,
) -> dict[str, Any]:
    config: dict[str, Any] = {"channel": int(channel), "interval_s": float(interval_s), "name": name}
    if points is not None:
        config["points"] = int(points)
    if duration_s is not None:
        config["duration_s"] = float(duration_s)
    return {"name": name, "measure": config}


def _measure_until(
    channel: int,
    interval_s: float,
    quantity: str,
    target: float,
    tolerance: float,
    settle_s: float,
    timeout_s: float,
    name: str,
) -> dict[str, Any]:
    return {
        "name": name,
        "measure_until": {
            "channel": int(channel),
            "interval_s": float(interval_s),
            "quantity": quantity,
            "target": float(target),
            "tolerance": float(tolerance),
            "require_stable": True,
            "settle_s": float(settle_s),
            "timeout_s": float(timeout_s),
            "name": name,
        },
    }
