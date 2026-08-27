"""Small verification helper for the lab MultiPyVu installation."""

from __future__ import annotations

import importlib.metadata
import sys


def main() -> int:
    try:
        import MultiPyVu as mpv
    except Exception as exc:
        print(f"FAILED: could not import MultiPyVu: {exc}")
        return 1

    try:
        version = importlib.metadata.version("MultiPyVu")
    except importlib.metadata.PackageNotFoundError:
        version = "unknown"

    print(f"MultiPyVu import OK: version={version}")
    print(f"module file: {getattr(mpv, '__file__', 'unknown')}")
    for attr in ("Client", "Server", "DataFile"):
        print(f"has {attr}: {hasattr(mpv, attr)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
