"""Scenario suite loader supporting YAML and JSON scenario definitions."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import yaml

from evalrunner.models import Scenario


def load_scenario_from_dict(data: dict[str, Any]) -> Scenario:
    """Validate and instantiate a Scenario model from dictionary data."""
    return Scenario.model_validate(data)


def load_scenario_file(file_path: str | Path) -> Scenario:
    """Load a single scenario file (.yaml, .yml, or .json)."""
    path = Path(file_path)
    if not path.is_file():
        raise FileNotFoundError(f"Scenario file not found: {path}")

    raw_text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(raw_text)
    elif path.suffix.lower() == ".json":
        data = json.loads(raw_text)
    else:
        raise ValueError(f"Unsupported scenario format: {path.suffix}")

    return load_scenario_from_dict(data)


def load_scenarios_from_directory(
    dir_path: str | Path,
    lang: str | None = None,
    group: str | None = None,
    scenario_ids: list[str] | None = None,
    locale: str | None = None,
) -> list[Scenario]:
    """Recursively load and filter scenarios from a directory."""
    path = Path(dir_path)
    if not path.is_dir():
        raise NotADirectoryError(f"Scenario directory not found: {path}")

    scenarios: list[Scenario] = []
    # Find all yaml/json files excluding schema.json or hidden files
    for file_path in sorted(path.rglob("*")):
        if file_path.is_file() and file_path.suffix.lower() in (
            ".yaml",
            ".yml",
            ".json",
        ):
            if file_path.name == "schema.json":
                continue
            if file_path.name.startswith("."):
                continue
            try:
                scenario = load_scenario_file(file_path)
            except Exception as exc:
                raise ValueError(
                    f"Failed to load scenario file '{file_path}': {exc}"
                ) from exc

            if lang and scenario.lang != lang:
                continue
            if locale and scenario.locale != locale:
                continue
            if group and scenario.group != group:
                continue
            if scenario_ids and scenario.id not in scenario_ids:
                continue

            scenarios.append(scenario)

    return scenarios
