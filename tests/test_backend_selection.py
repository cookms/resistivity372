from pathlib import Path

from resistivity372.runtime import RuntimeFactory


class FakeDataFile:
    def __init__(self, backend):
        self.backend = backend
        self.created_path = None
        self.records = []
        self._open = False

    @property
    def is_open(self):
        return self._open

    def create(self, path, metadata, allow_overwrite=False):
        self.created_path = Path(path)
        self.metadata = metadata
        self.allow_overwrite = allow_overwrite
        self._open = True

    def write_record(self, record):
        self.records.append(record)

    def close(self):
        self._open = False


def minimal_config(backend):
    return {
        "mode": {"simulation": True, "dry_run": True},
        "data": {"backend": backend, "allow_overwrite": True},
        "sample_metadata": {"sample_id": "T"},
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


def test_simulation_mode_does_not_force_multipyvu_backend_to_csv(monkeypatch, tmp_path):
    selected = []

    def fake_make_datafile_manager(backend):
        selected.append(backend)
        return FakeDataFile(backend)

    monkeypatch.setattr("resistivity372.runtime.make_datafile_manager", fake_make_datafile_manager)

    factory = RuntimeFactory()
    bundle = factory.create_bundle(
        config=minimal_config("multipyvu"),
        sequence_path="sequences/smoke_simulation.yaml",
        output_path=tmp_path / "out.dat",
        run_metadata={},
        connect=True,
    )

    try:
        assert selected == ["multipyvu"]
        assert bundle.datafile.metadata["data_backend"] == "multipyvu"
    finally:
        bundle.controllers.lakeshore.disconnect()
        bundle.controllers.ppms.disconnect()
        bundle.datafile.close()


def test_simulation_mode_keeps_csv_backend_when_config_requests_csv(monkeypatch, tmp_path):
    selected = []

    def fake_make_datafile_manager(backend):
        selected.append(backend)
        return FakeDataFile(backend)

    monkeypatch.setattr("resistivity372.runtime.make_datafile_manager", fake_make_datafile_manager)

    factory = RuntimeFactory()
    bundle = factory.create_bundle(
        config=minimal_config("csv"),
        sequence_path="sequences/smoke_simulation.yaml",
        output_path=tmp_path / "out.dat",
        run_metadata={},
        connect=True,
    )

    try:
        assert selected == ["csv"]
        assert bundle.datafile.metadata["data_backend"] == "csv"
    finally:
        bundle.controllers.lakeshore.disconnect()
        bundle.controllers.ppms.disconnect()
        bundle.datafile.close()


def test_can_select_real_lakeshore_and_real_multipyvu_client_from_config():
    config = minimal_config("csv")
    config["mode"]["simulation"] = False
    config["lakeshore372"] = {"simulation": False, "connection": {"mode": "gpib", "gpib_address": 12}}
    config["ppms"] = {"simulation": False, "host": "127.0.0.1", "port": 5000}

    from resistivity372.runtime import resolve_instrument_simulation_mode

    sim = resolve_instrument_simulation_mode(config)
    assert sim.global_simulation is False
    assert sim.lakeshore is False
    assert sim.ppms is False


def test_can_select_real_lakeshore_and_mock_ppms_from_config():
    config = minimal_config("csv")
    config["mode"]["simulation"] = False
    config["lakeshore372"] = {"simulation": False, "connection": {"mode": "gpib", "gpib_address": 12}}
    config["ppms"] = {"simulation": True, "host": "127.0.0.1", "port": 5000}

    from resistivity372.runtime import resolve_instrument_simulation_mode

    sim = resolve_instrument_simulation_mode(config)
    assert sim.global_simulation is False
    assert sim.lakeshore is False
    assert sim.ppms is True


def test_global_simulation_still_forces_both_instruments_to_mock():
    config = minimal_config("csv")
    config["mode"]["simulation"] = True
    config["lakeshore372"] = {"simulation": False, "connection": {"mode": "gpib", "gpib_address": 12}}
    config["ppms"] = {"simulation": False, "host": "127.0.0.1", "port": 5000}

    from resistivity372.runtime import resolve_instrument_simulation_mode

    sim = resolve_instrument_simulation_mode(config)
    assert sim.global_simulation is True
    assert sim.lakeshore is True
    assert sim.ppms is True
