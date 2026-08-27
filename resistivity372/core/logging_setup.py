from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(config: dict) -> Path:
    cfg = config.get("logging", {})
    log_dir = Path(cfg.get("log_dir", "./logs"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "resistivity372.log"

    level_name = str(cfg.get("level", "INFO")).upper()
    level = getattr(logging, level_name, logging.INFO)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_path,
        maxBytes=int(cfg.get("rotate_bytes", 5_000_000)),
        backupCount=int(cfg.get("backups", 10)),
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    root.addHandler(file_handler)

    return log_path
