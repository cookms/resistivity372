from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow running directly from a source checkout.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from resistivity372.instruments.lakeshore372 import (  # noqa: E402
    LakeShore372Config,
    RealLakeShore372Controller,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Connect to a Lake Shore 372 through GPIB/PyVISA and print a basic status."
    )
    parser.add_argument(
        "--resource",
        default=None,
        help="Full VISA resource string, e.g. GPIB0::12::INSTR.",
    )
    parser.add_argument("--board", type=int, default=0, help="GPIB board number if --resource is omitted.")
    parser.add_argument("--address", type=int, default=None, help="GPIB primary address if --resource is omitted.")
    parser.add_argument("--channel", default=None, help="Optional LS372 channel to read after connecting.")
    parser.add_argument("--timeout", type=float, default=2.0, help="VISA timeout in seconds.")
    args = parser.parse_args()

    if args.resource is None and args.address is None:
        parser.error("Provide either --resource or --address.")

    config = LakeShore372Config(
        mode="gpib",
        gpib_resource=args.resource,
        gpib_board=args.board,
        gpib_address=args.address,
        timeout_s=args.timeout,
    )
    controller = RealLakeShore372Controller(config)

    try:
        controller.connect()
        print("Connected to Lake Shore 372")
        print(controller.metadata())
        if args.channel is not None:
            print(controller.read_channel(args.channel))
        return 0
    finally:
        controller.disconnect()


if __name__ == "__main__":
    raise SystemExit(main())
