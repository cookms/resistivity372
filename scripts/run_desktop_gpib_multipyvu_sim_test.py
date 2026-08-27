from __future__ import annotations

import argparse
import sys
from datetime import datetime
from pathlib import Path

# Allow running this script directly from a source checkout before editable install.
REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

import yaml

from resistivity372.core.config import dotted_set, load_yaml_file
from resistivity372.core.logging_setup import setup_logging
from resistivity372.runtime import RuntimeFactory


DEFAULT_CONFIG = Path("configs/desktop_lakeshore_gpib_multipyvu_sim.yaml")
DEFAULT_SEQUENCE = Path("sequences/desktop_readonly_smoke.yaml")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Run a read-only desktop measurement using a real LS372 over GPIB "
            "and PPMS status from a MultiPyVu simulation/scaffolding server."
        )
    )
    parser.add_argument("--config", default=str(DEFAULT_CONFIG), help="Base YAML config path")
    parser.add_argument("--sequence", default=str(DEFAULT_SEQUENCE), help="Base read-only YAML sequence path")
    parser.add_argument("--gpib-resource", default=None, help="VISA resource, e.g. GPIB0::12::INSTR")
    parser.add_argument("--gpib-board", type=int, default=None, help="GPIB board number if no resource string is supplied")
    parser.add_argument("--gpib-address", type=int, default=None, help="GPIB primary address if no resource string is supplied")
    parser.add_argument("--channel", default=None, help="LS372 channel to read")
    parser.add_argument("--host", default=None, help="MultiPyVu server host, default from config")
    parser.add_argument("--port", type=int, default=None, help="MultiPyVu server port, default from config")
    parser.add_argument("--points", type=int, default=None, help="Number of measurement points")
    parser.add_argument("--interval", type=float, default=None, help="Measurement interval in seconds")
    parser.add_argument("--output", default=None, help="Output .dat path")
    parser.add_argument("--backend", choices=["multipyvu", "csv"], default=None, help="Data-file backend")
    parser.add_argument("--ppms-mock", action="store_true", help="Use the internal mock PPMS instead of MultiPyVu.Client")
    parser.add_argument("--allow-overwrite", action="store_true", help="Allow overwriting the output file")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    config_path = Path(args.config)
    sequence_path = Path(args.sequence)
    config = load_yaml_file(config_path)
    sequence = load_yaml_file(sequence_path)

    # Force mixed-mode semantics unless the caller deliberately edits the base config.
    dotted_set(config, "mode.simulation", False)
    dotted_set(config, "lakeshore372.simulation", False)
    dotted_set(config, "ppms.simulation", bool(args.ppms_mock))

    if args.gpib_resource is not None:
        dotted_set(config, "lakeshore372.connection.gpib_resource", args.gpib_resource)
    if args.gpib_board is not None:
        dotted_set(config, "lakeshore372.connection.gpib_board", args.gpib_board)
    if args.gpib_address is not None:
        dotted_set(config, "lakeshore372.connection.gpib_address", args.gpib_address)
    dotted_set(config, "lakeshore372.connection.mode", "gpib")

    if args.host is not None:
        dotted_set(config, "ppms.host", args.host)
    if args.port is not None:
        dotted_set(config, "ppms.port", args.port)
    if args.backend is not None:
        dotted_set(config, "data.backend", args.backend)

    channel = args.channel
    points = args.points
    interval = args.interval
    if channel is not None or points is not None or interval is not None:
        _override_measure_steps(sequence, channel=channel, points=points, interval=interval)

    output = Path(args.output) if args.output else _default_output_path(config)
    log_path = setup_logging(config)

    temp_sequence = output.with_suffix(output.suffix + ".sequence.yaml")
    temp_sequence.write_text(yaml.safe_dump(sequence, sort_keys=False), encoding="utf-8")

    print("Desktop mixed-mode test")
    print(f"  Config:      {config_path}")
    print(f"  Sequence:    {sequence_path}")
    print(f"  Temp seq:    {temp_sequence}")
    print(f"  Output:      {output}")
    print(f"  Log file:    {log_path}")
    print(f"  LS372 GPIB:  {config['lakeshore372']['connection'].get('gpib_resource')}")
    print(f"  PPMS mode:   {'internal mock' if args.ppms_mock else 'MultiPyVu.Client'}")
    if not args.ppms_mock:
        print(f"  MultiPyVu:   {config['ppms'].get('host')}:{config['ppms'].get('port')}")
    print("\nThis read-only sequence sends no PPMS setpoint commands.\n")

    factory = RuntimeFactory()
    bundle = factory.create_bundle(
        config=config,
        sequence_path=temp_sequence,
        output_path=output,
        run_metadata={
            "started_at": datetime.now().isoformat(),
            "script": "scripts/run_desktop_gpib_multipyvu_sim_test.py",
            "read_only_ppms": True,
        },
        allow_overwrite=args.allow_overwrite,
        on_record=lambda rec: print(
            "record "
            f"t={rec.elapsed_s:8.3f}s "
            f"T={rec.ppms.temperature_K} K "
            f"B={rec.ppms.field_T} T "
            f"R={rec.lakeshore.resistance_ohm} ohm "
            f"err={rec.error!r}"
        ),
        on_log=lambda msg: print(f"log: {msg}"),
    )

    try:
        bundle.runner.validate(sequence)
        bundle.runner.run(sequence)
        print(f"\nRun complete. Data file: {output}")
        return 0
    finally:
        try:
            bundle.datafile.close()
        finally:
            bundle.controllers.lakeshore.disconnect()
            bundle.controllers.ppms.disconnect()


def _override_measure_steps(sequence: dict, channel: str | None, points: int | None, interval: float | None) -> None:
    for step in sequence.get("steps", []):
        measure = step.get("measure")
        if not isinstance(measure, dict):
            continue
        if channel is not None:
            try:
                measure["channel"] = int(channel)
            except ValueError:
                measure["channel"] = channel
        if points is not None:
            measure["points"] = points
            measure.pop("duration_s", None)
        if interval is not None:
            measure["interval_s"] = interval


def _default_output_path(config: dict) -> Path:
    data_cfg = config.get("data", {})
    output_dir = Path(data_cfg.get("output_dir", "."))
    date = datetime.now().strftime("%Y%m%d_%H%M%S")
    template = data_cfg.get("filename_template", "desktop_gpib_multipyvu_sim_{date}.dat")
    sample_id = config.get("sample_metadata", {}).get("sample_id", "Desktop-GPIB-Test")
    return output_dir / template.format(sample_id=sample_id, date=date)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
