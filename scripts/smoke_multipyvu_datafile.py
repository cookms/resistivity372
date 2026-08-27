"""Create a tiny MultiPyVu.DataFile-backed .dat file for lab verification.

This script uses mock instruments but forces data.backend='multipyvu'. It is intended
for the lab Windows environment after installing requirements-lab.txt. The output
should contain a MultiVu-style [Header] / [Data] structure, not the CSV fallback
header.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from resistivity372.core.config import dotted_set, load_yaml_file
from resistivity372.runtime import RuntimeFactory
from resistivity372.measurement.sequence import load_sequence


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Smoke-test the MultiPyVu data-file backend.")
    parser.add_argument("--config", default="configs/example_config.yaml")
    parser.add_argument("--sequence", default="sequences/smoke_simulation.yaml")
    parser.add_argument("--output", default="multipyvu_backend_smoke.dat")
    parser.add_argument("--allow-overwrite", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = load_yaml_file(args.config)
    dotted_set(config, "mode.simulation", True)
    dotted_set(config, "mode.dry_run", True)
    dotted_set(config, "data.backend", "multipyvu")

    factory = RuntimeFactory()
    bundle = factory.create_bundle(
        config=config,
        sequence_path=args.sequence,
        output_path=Path(args.output),
        run_metadata={"script": "smoke_multipyvu_datafile.py"},
        allow_overwrite=args.allow_overwrite,
        on_log=lambda message: print(message),
    )

    try:
        sequence = load_sequence(args.sequence)
        bundle.runner.validate(sequence)
        bundle.runner.run(sequence)
    finally:
        bundle.datafile.close()
        bundle.controllers.lakeshore.disconnect()
        bundle.controllers.ppms.disconnect()

    print(f"Created MultiPyVu data-file smoke output: {Path(args.output).resolve()}")
    print("Inspect the file for [Header] and [Data], then open it in MultiVu.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
