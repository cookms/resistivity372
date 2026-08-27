from __future__ import annotations

import argparse
import logging
import sys
from datetime import datetime
from pathlib import Path

from resistivity372.core.config import dotted_set, load_yaml_file
from resistivity372.core.geometry import geometry_from_config
from resistivity372.core.logging_setup import setup_logging
from resistivity372.core.safety import safety_from_config
from resistivity372.measurement.sequence import load_sequence
from resistivity372.measurement.sequence_runner import validate_sequence_against_safety
from resistivity372.runtime import RuntimeFactory

log = logging.getLogger(__name__)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="LS372 + PPMS/MultiPyVu resistivity backbone")
    parser.add_argument("--config", default="configs/example_config.yaml", help="YAML config path")
    parser.add_argument("--sequence", default=None, help="YAML sequence path")
    parser.add_argument("--output", default=None, help="Output data path")
    parser.add_argument("--simulate", action="store_true", help="Use mock instruments")
    parser.add_argument("--dry-run", action="store_true", help="Validate/log commands but do not send real PPMS setpoints")
    parser.add_argument("--allow-overwrite", action="store_true", help="Allow overwriting existing output file")
    parser.add_argument("--validate-only", action="store_true", help="Load and validate config/sequence, then exit")
    parser.add_argument("--gui", action="store_true", help="Start the PySide6 measurement GUI")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.gui:
        try:
            from resistivity372.app.gui_main import run_gui
        except Exception as exc:  # pragma: no cover - optional GUI dependency
            print(
                "PySide6 and pyqtgraph are required for the GUI. "
                "Install with: pip install -e .[gui]",
                file=sys.stderr,
            )
            print(str(exc), file=sys.stderr)
            return 2
        return run_gui(args)

    config = load_yaml_file(args.config)
    if args.simulate:
        # Simulation controls only the instrument layer. Do not silently force
        # CSV output here: users may want mock instruments plus a real
        # MultiPyVu.DataFile backend to validate MultiVu-compatible files.
        dotted_set(config, "mode.simulation", True)
    if args.dry_run:
        dotted_set(config, "mode.dry_run", True)

    log_path = setup_logging(config)
    log.info("Logging to %s", log_path)

    if args.sequence is None:
        print("No --sequence provided. Use --validate-only with a sequence or start --gui.")
        return 2

    sequence = load_sequence(args.sequence)
    output = Path(args.output) if args.output else default_output_path(config)

    if args.validate_only:
        geometry_from_config(config)
        validate_sequence_against_safety(sequence, safety_from_config(config))
        print(f"Validated config: {args.config}")
        print(f"Validated sequence: {args.sequence}")
        print(f"Output would be: {output}")
        return 0

    factory = RuntimeFactory()
    bundle = factory.create_bundle(
        config=config,
        sequence_path=args.sequence,
        output_path=output,
        run_metadata={"started_at": datetime.now().astimezone().isoformat(), "cli": True},
        simulate=bool(config.get("mode", {}).get("simulation", False)),
        dry_run=bool(config.get("mode", {}).get("dry_run", False)),
        allow_overwrite=args.allow_overwrite,
        on_record=lambda rec: log.info(
            "record: t=%.3f s T=%s K B=%s T R=%s ohm rho=%s ohm m",
            rec.elapsed_s,
            rec.ppms.temperature_K,
            rec.ppms.field_T,
            rec.lakeshore.resistance_ohm,
            rec.resistivity_ohm_m,
        ),
        on_log=lambda msg: log.info("sequence: %s", msg),
    )

    try:
        bundle.runner.validate(sequence)
        bundle.runner.run(sequence)
        print(f"Run complete. Data file: {output}")
        return 0
    finally:
        try:
            bundle.datafile.close()
        finally:
            bundle.controllers.lakeshore.disconnect()
            bundle.controllers.ppms.disconnect()


def default_output_path(config: dict) -> Path:
    data_cfg = config.get("data", {})
    output_dir = Path(data_cfg.get("output_dir", "."))
    sample_id = config.get("sample_metadata", {}).get("sample_id", "sample")
    template = data_cfg.get("filename_template", "{sample_id}_{date}_LS372_resistivity.dat")
    date = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
    return output_dir / template.format(sample_id=sample_id, date=date)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
