from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any

from resistivity372.core.config import deep_update
from resistivity372.measurement.sequence import expanded_steps


class ApplicationState(str, Enum):
    IDLE = "IDLE"
    CONFIGURING = "CONFIGURING"
    READY = "READY"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    ABORTING = "ABORTING"
    COMPLETED = "COMPLETED"
    ERROR = "ERROR"


@dataclass(frozen=True)
class ControlAvailability:
    start: bool = False
    pause: bool = False
    resume: bool = False
    abort: bool = False
    configure: bool = True


def controls_for_state(state: ApplicationState, run_ready: bool = False) -> ControlAvailability:
    if state is ApplicationState.READY:
        return ControlAvailability(start=run_ready)
    if state is ApplicationState.RUNNING:
        return ControlAvailability(pause=True, abort=True, configure=False)
    if state is ApplicationState.PAUSED:
        return ControlAvailability(resume=True, abort=True, configure=False)
    if state in {ApplicationState.STARTING, ApplicationState.ABORTING}:
        return ControlAvailability(configure=False)
    return ControlAvailability()


@dataclass(frozen=True)
class SampleMetadata:
    sample_id: str = ""
    material: str = ""
    contact_configuration: str = ""
    orientation: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value.strip()}


@dataclass(frozen=True)
class RunMetadata:
    operator: str = ""
    experiment_name: str = ""
    lab_notebook_reference: str = ""
    cooldown_id: str = ""
    notes: str = ""

    def to_dict(self) -> dict[str, str]:
        return {key: value for key, value in asdict(self).items() if value.strip()}


@dataclass(frozen=True)
class SequenceSummary:
    expanded_steps: int
    temperature_targets_K: tuple[float, ...] = ()
    field_targets_T: tuple[float, ...] = ()
    temperature_rates_K_per_min: tuple[float, ...] = ()
    field_rates_T_per_min: tuple[float, ...] = ()
    measurement_channels: tuple[str, ...] = ()
    acquisition_points: int = 0
    acquisition_duration_s: float = 0.0
    has_chamber_commands: bool = False
    has_position_commands: bool = False

    @property
    def temperature_extrema(self) -> tuple[float, float] | None:
        if not self.temperature_targets_K:
            return None
        return min(self.temperature_targets_K), max(self.temperature_targets_K)

    @property
    def field_extrema(self) -> tuple[float, float] | None:
        if not self.field_targets_T:
            return None
        return min(self.field_targets_T), max(self.field_targets_T)

    def to_text(self) -> str:
        parts = [f"Expanded steps: {self.expanded_steps}"]
        if self.temperature_targets_K:
            parts.append("Temperature targets (K): " + ", ".join(_format_values(self.temperature_targets_K)))
        if self.field_targets_T:
            parts.append("Field targets (T): " + ", ".join(_format_values(self.field_targets_T)))
        if self.temperature_rates_K_per_min:
            parts.append("Temperature ramps (K/min): " + ", ".join(_format_values(self.temperature_rates_K_per_min)))
        if self.field_rates_T_per_min:
            parts.append("Field ramps (T/min): " + ", ".join(_format_values(self.field_rates_T_per_min)))
        if self.measurement_channels:
            parts.append("Measurement channel(s): " + ", ".join(self.measurement_channels))
        if self.acquisition_points:
            parts.append(f"Acquisition points: {self.acquisition_points}")
        if self.acquisition_duration_s:
            parts.append(f"Duration-based acquisition: {self.acquisition_duration_s:g} s total")
        parts.append(f"Chamber commands: {'yes' if self.has_chamber_commands else 'no'}")
        parts.append(f"Position commands: {'yes' if self.has_position_commands else 'no'}")
        return "\n".join(parts)


@dataclass
class RunPreparation:
    config_path: Path | None = None
    sequence_path: Path | None = None
    output_path: Path | None = None
    sequence_valid: bool = False
    run_initialized: bool = False
    allow_overwrite: bool = False
    validation_fingerprint: str = ""
    summary: SequenceSummary | None = None
    errors: list[str] = field(default_factory=list)

    @property
    def ready(self) -> bool:
        return bool(
            self.config_path
            and self.sequence_path
            and self.output_path
            and self.sequence_valid
            and self.run_initialized
            and not self.errors
        )

    def invalidate_run(self) -> None:
        self.run_initialized = False
        self.allow_overwrite = False


def build_effective_config(
    base_config: dict[str, Any],
    sample: SampleMetadata,
    run: RunMetadata,
    geometry_config: dict[str, Any],
) -> dict[str, Any]:
    """Apply explicit per-run GUI overrides to a base YAML configuration."""
    metadata = dict(base_config.get("sample_metadata", {}))
    metadata.update(sample.to_dict())
    metadata.update(run.to_dict())
    return deep_update(
        base_config,
        {
            "sample_metadata": metadata,
            "sample_geometry": geometry_config,
        },
    )


def compose_run_metadata(
    sample: SampleMetadata,
    run: RunMetadata,
    geometry_config: dict[str, Any],
    output_path: str | Path,
    backend: str,
    simulation: dict[str, bool],
    dry_run: bool,
) -> dict[str, Any]:
    return {
        "sample": sample.to_dict(),
        "run": run.to_dict(),
        "sample_geometry": geometry_config,
        "output_path": str(Path(output_path)),
        "data_backend": backend,
        "instrument_simulation": dict(simulation),
        "dry_run": bool(dry_run),
        "started_at": datetime.now().astimezone().isoformat(),
        "gui": True,
    }


def summarize_sequence(sequence: dict[str, Any]) -> SequenceSummary:
    steps = list(expanded_steps(sequence.get("steps", [])))
    temperatures: set[float] = set()
    fields: set[float] = set()
    temp_rates: set[float] = set()
    field_rates: set[float] = set()
    channels: set[str] = set()
    points = 0
    duration = 0.0
    chamber = False
    position = False

    for step in steps:
        if "set_temperature" in step:
            cfg = step["set_temperature"]
            temperatures.add(float(cfg["setpoint_K"]))
            temp_rates.add(float(cfg["rate_K_per_min"]))
        if "set_field" in step:
            cfg = step["set_field"]
            fields.add(float(cfg["setpoint_T"]))
            field_rates.add(float(cfg["rate_T_per_min"]))
        if "measure" in step:
            cfg = step["measure"]
            channels.add(str(cfg.get("channel", 1)))
            if cfg.get("points") is not None:
                points += int(cfg["points"])
            if cfg.get("duration_s") is not None:
                duration += float(cfg["duration_s"])
        chamber = chamber or "set_chamber" in step
        position = position or "set_position" in step

    return SequenceSummary(
        expanded_steps=len(steps),
        temperature_targets_K=tuple(sorted(temperatures)),
        field_targets_T=tuple(sorted(fields)),
        temperature_rates_K_per_min=tuple(sorted(temp_rates)),
        field_rates_T_per_min=tuple(sorted(field_rates)),
        measurement_channels=tuple(sorted(channels)),
        acquisition_points=points,
        acquisition_duration_s=duration,
        has_chamber_commands=chamber,
        has_position_commands=position,
    )


def suggested_filename(sample_id: str, experiment_name: str = "") -> str:
    stem_parts = [_safe_stem(sample_id) or "sample"]
    if experiment_name.strip():
        stem_parts.append(_safe_stem(experiment_name))
    stem_parts.append(datetime.now().astimezone().strftime("%Y%m%d_%H%M%S"))
    return "_".join(part for part in stem_parts if part) + "_LS372_resistivity.dat"


def _safe_stem(value: str) -> str:
    return "_".join(value.strip().split()).replace("/", "-").replace("\\", "-")


def _format_values(values: tuple[float, ...]) -> list[str]:
    return [f"{value:g}" for value in values]
