from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import yaml


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(base)
    for key, value in override.items():
        if (
            key in result
            and isinstance(result[key], dict)
            and isinstance(value, dict)
        ):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = deepcopy(value)
    return result


def load_tuning(path: str | Path) -> dict[str, Any]:
    tuning_path = Path(path)
    if not tuning_path.exists():
        return {}

    data = yaml.safe_load(
        tuning_path.read_text(encoding="utf-8")
    ) or {}
    if not isinstance(data, dict):
        raise ValueError(
            f"Tuning file must contain a mapping: {tuning_path}"
        )
    return data


def apply_tuning(
    config: dict[str, Any],
    tuning_path: str | Path | None,
) -> tuple[dict[str, Any], bool]:
    if tuning_path is None:
        return deepcopy(config), False

    tuning = load_tuning(tuning_path)
    if not tuning:
        return deepcopy(config), False

    return deep_merge(config, tuning), True


def save_tuning(
    path: str | Path,
    tuning: dict[str, Any],
) -> None:
    tuning_path = Path(path)
    tuning_path.parent.mkdir(parents=True, exist_ok=True)
    tuning_path.write_text(
        yaml.safe_dump(tuning, sort_keys=False),
        encoding="utf-8",
    )
