from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Iterator

from resistivity372.core.config import load_yaml_file
from resistivity372.core.exceptions import SequenceValidationError


def load_sequence(path: str | Path) -> dict[str, Any]:
    seq = load_yaml_file(path)
    if seq.get("version") != 1:
        raise SequenceValidationError("Only sequence version 1 is supported.")
    if not isinstance(seq.get("steps"), list):
        raise SequenceValidationError("Sequence must have a steps list.")
    return seq


def expanded_steps(steps: list[dict[str, Any]]) -> Iterator[dict[str, Any]]:
    for step in steps:
        if "loop" not in step:
            yield step
            continue
        loop = step["loop"]
        variable = loop["variable"]
        for value in loop_values(loop):
            for inner in loop["steps"]:
                expanded = substitute(copy.deepcopy(inner), variable, value)
                yield expanded


def loop_values(loop: dict[str, Any]) -> list[float]:
    if "values" in loop:
        return [float(v) for v in loop["values"]]

    try:
        start = float(loop["start"])
        stop = float(loop["stop"])
        step = float(loop["step"])
    except KeyError as exc:
        raise SequenceValidationError(f"Loop missing required key: {exc}") from exc

    if step == 0:
        raise SequenceValidationError("Loop step cannot be zero.")

    values: list[float] = []
    x = start
    if step > 0:
        while x <= stop + abs(step) * 1e-12:
            values.append(round(x, 12))
            x += step
    else:
        while x >= stop - abs(step) * 1e-12:
            values.append(round(x, 12))
            x += step
    return values


def substitute(obj, variable: str, value: float):
    token = "${" + variable + "}"
    if isinstance(obj, str):
        text = obj.replace(token, str(value))
        try:
            return float(text) if text == str(value) else text
        except ValueError:
            return text
    if isinstance(obj, dict):
        return {k: substitute(v, variable, value) for k, v in obj.items()}
    if isinstance(obj, list):
        return [substitute(v, variable, value) for v in obj]
    return obj
