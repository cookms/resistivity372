from __future__ import annotations

from pathlib import Path
from typing import Any


class ConfigError(ValueError):
    """Raised when a configuration file cannot be loaded or interpreted."""


def load_yaml_file(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    try:
        import yaml
    except Exception as exc:
        raise ConfigError("PyYAML is required to load YAML files.") from exc

    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ConfigError(f"Expected mapping at top level of {path}")
    return data


def deep_update(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    result = dict(base)
    for key, value in updates.items():
        if isinstance(value, dict) and isinstance(result.get(key), dict):
            result[key] = deep_update(result[key], value)
        else:
            result[key] = value
    return result


def dotted_get(mapping: dict[str, Any], dotted_key: str, default=None):
    current = mapping
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return default
        current = current[part]
    return current


def dotted_set(mapping: dict[str, Any], dotted_key: str, value) -> None:
    current = mapping
    parts = dotted_key.split(".")
    for part in parts[:-1]:
        current = current.setdefault(part, {})
    current[parts[-1]] = value
