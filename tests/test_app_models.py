from resistivity372.app.models import (
    ApplicationState,
    RunMetadata,
    SampleMetadata,
    build_effective_config,
    compose_run_metadata,
    controls_for_state,
    summarize_sequence,
)


def test_metadata_omits_incomplete_optional_values():
    sample = SampleMetadata(sample_id="S-1", material="", orientation="ab plane")
    run = RunMetadata(operator="Operator", experiment_name="")

    assert sample.to_dict() == {"sample_id": "S-1", "orientation": "ab plane"}
    assert run.to_dict() == {"operator": "Operator"}


def test_effective_config_applies_gui_overrides_without_mutating_base():
    base = {
        "sample_metadata": {"sample_id": "old", "description": "kept"},
        "sample_geometry": {},
        "data": {"backend": "csv"},
    }
    geometry = {"length": {"value": 1.0, "unit": "mm"}}
    effective = build_effective_config(
        base,
        SampleMetadata(sample_id="new"),
        RunMetadata(operator="Ada"),
        geometry,
    )

    assert base["sample_metadata"]["sample_id"] == "old"
    assert effective["sample_metadata"] == {
        "sample_id": "new",
        "description": "kept",
        "operator": "Ada",
    }
    assert effective["sample_geometry"] == geometry


def test_run_metadata_records_backend_modes_and_geometry(tmp_path):
    metadata = compose_run_metadata(
        SampleMetadata(sample_id="S"),
        RunMetadata(),
        {},
        tmp_path / "run.dat",
        "multipyvu",
        {"global": False, "lakeshore": False, "ppms": True},
        True,
    )

    assert metadata["data_backend"] == "multipyvu"
    assert metadata["instrument_simulation"]["ppms"] is True
    assert metadata["dry_run"] is True
    assert metadata["sample"] == {"sample_id": "S"}


def test_sequence_summary_expands_loops_and_counts_acquisition():
    sequence = {
        "version": 1,
        "steps": [
            {
                "loop": {
                    "variable": "field",
                    "values": [-1, 1],
                    "steps": [
                        {
                            "set_field": {
                                "setpoint_T": "${field}",
                                "rate_T_per_min": 0.1,
                            }
                        },
                        {"measure": {"channel": 2, "points": 3, "interval_s": 1}},
                    ],
                }
            }
        ],
    }

    summary = summarize_sequence(sequence)
    assert summary.expanded_steps == 4
    assert summary.field_extrema == (-1.0, 1.0)
    assert summary.acquisition_points == 6
    assert summary.measurement_channels == ("2",)


def test_control_availability_enforces_state_machine():
    assert controls_for_state(ApplicationState.READY, run_ready=True).start is True
    assert controls_for_state(ApplicationState.RUNNING).pause is True
    assert controls_for_state(ApplicationState.RUNNING).configure is False
    assert controls_for_state(ApplicationState.PAUSED).resume is True
    assert controls_for_state(ApplicationState.ABORTING).abort is False
