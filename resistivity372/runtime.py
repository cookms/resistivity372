from __future__ import annotations

import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from resistivity372.core.geometry import geometry_from_config
from resistivity372.core.safety import safety_from_config
from resistivity372.instruments.lakeshore372 import LakeShore372Config, RealLakeShore372Controller
from resistivity372.instruments.mocks import MockLakeShore372Controller, MockPPMSController
from resistivity372.instruments.ppms_multipyvu import PPMSConfig, RealPPMSController
from resistivity372.measurement.datafile_manager import DataFileWriter, make_datafile_manager
from resistivity372.measurement.engine import ResistivityMeasurementEngine
from resistivity372.measurement.sequence import load_sequence
from resistivity372.measurement.sequence_runner import SequenceRunner


@dataclass
class Controllers:
    lakeshore: object
    ppms: object


@dataclass(frozen=True)
class InstrumentSimulationMode:
    """Resolved per-instrument simulation flags.

    `global_simulation=True` means both instruments are mocked, preserving the original
    behavior of mode.simulation and the --simulate CLI option. Otherwise each instrument
    can be controlled independently with lakeshore372.simulation and ppms.simulation.
    """

    global_simulation: bool
    lakeshore: bool
    ppms: bool


@dataclass
class RuntimeBundle:
    controllers: Controllers
    datafile: DataFileWriter
    engine: ResistivityMeasurementEngine
    runner: SequenceRunner


def resolve_instrument_simulation_mode(
    config: dict,
    simulate: bool | None = None,
) -> InstrumentSimulationMode:
    """Resolve global and per-instrument simulation settings.

    Backward-compatible rules:
    - If `simulate` is explicitly True, or mode.simulation is True, both instruments are mocked.
    - If global simulation is False, lakeshore372.simulation and ppms.simulation can be set
      independently.
    - Missing per-instrument flags default to False when global simulation is False.

    This enables desktop mixed-mode tests such as:
    real LS372 over GPIB + real MultiPyVu.Client connected to a MultiPyVu scaffolding server.
    """

    mode = config.get("mode", {})
    global_simulation = bool(mode.get("simulation", False) if simulate is None else simulate)
    if global_simulation:
        return InstrumentSimulationMode(global_simulation=True, lakeshore=True, ppms=True)

    lakeshore_sim = bool(config.get("lakeshore372", {}).get("simulation", False))
    ppms_sim = bool(config.get("ppms", {}).get("simulation", False))
    return InstrumentSimulationMode(
        global_simulation=False,
        lakeshore=lakeshore_sim,
        ppms=ppms_sim,
    )


class RuntimeFactory:
    def __init__(self):
        self._datafile: DataFileWriter | None = None

    def create_controllers(self, config: dict, simulate: bool | None = None, dry_run: bool | None = None) -> Controllers:
        mode = config.get("mode", {})
        dry_run = bool(mode.get("dry_run", False) if dry_run is None else dry_run)
        safety = safety_from_config(config)
        sim_mode = resolve_instrument_simulation_mode(config, simulate=simulate)

        lakeshore = (
            MockLakeShore372Controller()
            if sim_mode.lakeshore
            else RealLakeShore372Controller(LakeShore372Config.from_config(config))
        )
        ppms = (
            MockPPMSController(safety=safety)
            if sim_mode.ppms
            else RealPPMSController(PPMSConfig.from_config(config), safety=safety, dry_run=dry_run)
        )
        return Controllers(lakeshore=lakeshore, ppms=ppms)

    def create_bundle(
        self,
        config: dict,
        sequence_path: str | Path,
        output_path: str | Path,
        run_metadata: dict,
        simulate: bool | None = None,
        dry_run: bool | None = None,
        allow_overwrite: bool | None = None,
        abort_flag: threading.Event | None = None,
        pause_flag: threading.Event | None = None,
        on_record: Callable | None = None,
        on_log: Callable | None = None,
        on_step: Callable | None = None,
        connect: bool = True,
        controllers: Controllers | None = None,
    ) -> RuntimeBundle:
        sim_mode = resolve_instrument_simulation_mode(config, simulate=simulate)
        controllers = controllers or self.create_controllers(
            config, simulate=simulate, dry_run=dry_run
        )
        datafile: DataFileWriter | None = None
        try:
            if connect:
                if not controllers.lakeshore.is_connected:
                    controllers.lakeshore.connect()
                if not controllers.ppms.is_connected:
                    controllers.ppms.connect()

            data_cfg = config.get("data", {})
            backend = str(data_cfg.get("backend", "multipyvu")).lower()
            allow_overwrite = bool(
                data_cfg.get("allow_overwrite", False)
                if allow_overwrite is None
                else allow_overwrite
            )
            datafile = make_datafile_manager(backend)
            if on_log is not None:
                on_log(f"Using data-file backend: {backend}")
                on_log(
                    "Instrument simulation: "
                    f"lakeshore={sim_mode.lakeshore}, ppms={sim_mode.ppms}, "
                    f"global={sim_mode.global_simulation}"
                )
            sequence = load_sequence(sequence_path)
            metadata = {
                "config_sample_metadata": config.get("sample_metadata", {}),
                "sample_geometry": config.get("sample_geometry", {}),
                "sequence_metadata": sequence.get("metadata", {}),
                "run_metadata": run_metadata,
                "data_backend": backend,
                "dry_run": bool(config.get("mode", {}).get("dry_run", False)),
                "instrument_simulation": {
                    "global": sim_mode.global_simulation,
                    "lakeshore": sim_mode.lakeshore,
                    "ppms": sim_mode.ppms,
                },
                "lakeshore": controllers.lakeshore.metadata(),
            }
            datafile.create(output_path, metadata=metadata, allow_overwrite=allow_overwrite)
            self._datafile = datafile

            abort_flag = abort_flag or threading.Event()
            pause_flag = pause_flag or threading.Event()
            geometry = geometry_from_config(config)
            safety = safety_from_config(config)
            engine = ResistivityMeasurementEngine(
                lakeshore=controllers.lakeshore,
                ppms=controllers.ppms,
                datafile=datafile,
                geometry=geometry,
                abort_flag=abort_flag,
                pause_flag=pause_flag,
                on_record=on_record,
                on_log=on_log,
            )
            runner = SequenceRunner(
                ppms=controllers.ppms,
                lakeshore=controllers.lakeshore,
                engine=engine,
                safety=safety,
                abort_flag=abort_flag,
                pause_flag=pause_flag,
                dry_run=bool(config.get("mode", {}).get("dry_run", False)),
                on_step=on_step,
                on_log=on_log,
            )
            return RuntimeBundle(
                controllers=controllers,
                datafile=datafile,
                engine=engine,
                runner=runner,
            )
        except Exception:
            try:
                if datafile is not None:
                    datafile.close()
            finally:
                if connect:
                    try:
                        controllers.lakeshore.disconnect()
                    finally:
                        controllers.ppms.disconnect()
            raise

    def close_datafile(self) -> None:
        if self._datafile is not None:
            self._datafile.close()
