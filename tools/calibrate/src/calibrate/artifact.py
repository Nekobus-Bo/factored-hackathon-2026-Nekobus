"""Writing the calibration artifact (ADR-0012, Appendix B and F).

``packages/encoder/calibration/decision_points.json`` is written only by the
harness. A calibration run produces *fragments*, one per decision point: that DP's
entry plus the spec of the backend it was fitted on. ``merge_fragments`` replaces
those DPs in the existing artifact and leaves every other DP alone, so recalibrating
``confirm_gate`` cannot move ``block_reason``.

The one thing a merge refuses is to change a backend under a DP that is not being
recalibrated: a tau never travels without the model it was fitted on, so a backend
whose pin changes takes every DP that reads it into the same run.

Nothing here trains a model or reads a data file. It works on decoded JSON and hands
the result to the encoder's own schema (``encoder.decision_points``) for validation
and for the canonical ``artifact_id``.
"""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from encoder.decision_points import (
    SCHEMA_VERSION,
    ArtifactError,
    BackendSpec,
    DecisionPointSpec,
    artifact_to_json,
    parse_artifact,
)

Json = dict[str, Any]


class ArtifactMergeError(ValueError):
    """The run cannot be merged into the artifact without breaking it. The message
    says what to change."""


@dataclass(frozen=True)
class RunMeta:
    """Provenance of the latest run, written at the top of the artifact."""

    created_at: str
    git_sha: str | None
    config_path: str | None
    config_sha256: str | None


def canonical_json(value: Any) -> str:
    """The one text form used to hash and to embed JSON in a report."""
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False)


def compact_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def fragment(
    dp_id: str, entry: Mapping[str, Any], backend_id: str, backend: Mapping[str, Any]
) -> Json:
    """One DP's slice of the artifact: its entry and the backend it was fitted on."""
    return {
        "backends": {backend_id: copy.deepcopy(dict(backend))},
        "decision_points": {dp_id: copy.deepcopy(dict(entry))},
    }


def fragment_of(artifact: Mapping[str, Any], dp_id: str) -> Json:
    """The fragment of ``dp_id`` as the artifact holds it (what a report embeds)."""
    entry = artifact["decision_points"][dp_id]
    backend_id = entry["backend"]
    return fragment(dp_id, entry, backend_id, artifact["backends"][backend_id])


def fragment_text(frag: Mapping[str, Any]) -> str:
    """The exact text a report embeds and ``calibration-verify`` looks for."""
    return canonical_json(frag)


def validate_entry(dp_id: str, entry: Mapping[str, Any]) -> None:
    """Fail early, with the DP's name, if an entry would not load."""
    try:
        DecisionPointSpec.model_validate(entry)
    except ValueError as exc:
        raise ArtifactMergeError(f"decision point '{dp_id}': {exc}") from exc


def validate_backend(backend_id: str, spec: Mapping[str, Any]) -> None:
    try:
        BackendSpec.model_validate(spec)
    except ValueError as exc:
        raise ArtifactMergeError(f"backend '{backend_id}': {exc}") from exc


def load_raw(path: Path | str) -> Json | None:
    """The artifact at ``path`` as decoded JSON, or None if there is no file.

    An existing file must be valid and untouched by hand: a merge starts from it, so
    one that fails its own checks would bless whatever is wrong with it.
    """
    file = Path(path)
    if not file.is_file():
        return None
    try:
        raw = json.loads(file.read_text(encoding="utf-8"))
        parse_artifact(raw, str(file))
    except (ValueError, ArtifactError) as exc:
        raise ArtifactMergeError(
            f"{file} is not a valid calibration artifact ({exc}). "
            "Restore it (git checkout) or delete it and recalibrate every decision "
            "point; the harness will not merge into a file that fails its checks"
        ) from exc
    return raw  # type: ignore[no-any-return]


def summarize_data(decision_points: Mapping[str, Mapping[str, Any]]) -> Json | None:
    """The top-level ``data`` block, from what every DP's evidence says it used.

    A hash appears only when every DP agrees on it; a provenance is the weakest
    any DP was scored on (``synthetic-provisional`` < ``synthetic`` < ``human``).
    """
    order = ["synthetic-provisional", "synthetic", "human"]
    hashes: dict[str, set[str]] = {"train": set(), "validation": set(), "test": set()}
    provenances: list[str] = []
    for entry in decision_points.values():
        data = entry.get("evidence", {}).get("data", {})
        for split in hashes:
            block = data.get(split)
            if isinstance(block, Mapping) and block.get("sha256"):
                hashes[split].add(block["sha256"])
        provenance = entry.get("evidence", {}).get("provenance")
        if provenance in order:
            provenances.append(provenance)
    summary: Json = {}
    for split, values in hashes.items():
        if len(values) == 1:
            summary[f"{split}_sha256"] = next(iter(values))
    if provenances:
        summary["test_provenance"] = min(provenances, key=order.index)
    return summary or None


def merge_fragments(
    existing: Mapping[str, Any] | None,
    fragments: Sequence[Mapping[str, Any]],
    meta: RunMeta,
) -> Json:
    """The artifact after replacing the fragments' decision points in ``existing``.

    Other decision points and their backends are kept byte for byte. Backends no
    decision point reads any more are dropped. ``artifact_id`` is recomputed.
    """
    if not fragments:
        raise ArtifactMergeError("nothing to merge: the run produced no decision point")
    merged: Json = (
        copy.deepcopy(dict(existing))
        if existing is not None
        else {"schema_version": SCHEMA_VERSION, "backends": {}, "decision_points": {}}
    )

    new_backends: dict[str, Json] = {}
    new_points: dict[str, Json] = {}
    for frag in fragments:
        for backend_id, spec in frag["backends"].items():
            validate_backend(backend_id, spec)
            if backend_id in new_backends and new_backends[backend_id] != spec:
                raise ArtifactMergeError(
                    f"two decision points of this run describe backend '{backend_id}' "
                    "differently; one backend id names one model"
                )
            new_backends[backend_id] = copy.deepcopy(dict(spec))
        for dp_id, entry in frag["decision_points"].items():
            if dp_id in new_points:
                raise ArtifactMergeError(
                    f"decision point '{dp_id}' appears twice in this run"
                )
            validate_entry(dp_id, entry)
            new_points[dp_id] = copy.deepcopy(dict(entry))

    for backend_id, spec in new_backends.items():
        old = merged["backends"].get(backend_id)
        if old is None or old == spec:
            continue
        stranded = sorted(
            dp_id
            for dp_id, entry in merged["decision_points"].items()
            if entry["backend"] == backend_id and dp_id not in new_points
        )
        if stranded:
            raise ArtifactMergeError(
                f"backend '{backend_id}' changed (model_id {old.get('model_id')} -> "
                f"{spec.get('model_id')}), but decision points {stranded} still use "
                "it and were fitted on the old model. Recalibrate them in the same "
                "run (omit DP=) or give the new model another backend name"
            )

    merged["backends"].update(new_backends)
    merged["decision_points"].update(new_points)
    used = {entry["backend"] for entry in merged["decision_points"].values()}
    for backend_id in sorted(set(merged["backends"]) - used):
        del merged["backends"][backend_id]

    merged["schema_version"] = SCHEMA_VERSION
    merged["created_at"] = meta.created_at
    merged["harness"] = {
        "git_sha": meta.git_sha,
        "config_path": meta.config_path,
        "config_sha256": meta.config_sha256,
    }
    data = summarize_data(merged["decision_points"])
    if data is None:
        merged.pop("data", None)
    else:
        merged["data"] = data
    return json.loads(artifact_to_json(merged))  # type: ignore[no-any-return]


def write_artifact(path: Path | str, raw: Mapping[str, Any]) -> str:
    """Validate ``raw`` with the encoder's schema and write it atomically.

    Returns the new ``artifact_id``. The file is deterministic (sorted keys, fixed
    indent, trailing newline), so a diff shows only what changed.
    """
    text = artifact_to_json(raw)
    try:
        artifact = parse_artifact(json.loads(text), str(path))
    except ArtifactError as exc:
        raise ArtifactMergeError(f"the merged artifact would not load: {exc}") from exc
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        dir=target.parent, prefix=f".{target.name}.", suffix=".tmp"
    )
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as out:
            out.write(text)
        # mkstemp creates 0600; the encoder image reads it as a non-root user.
        os.chmod(temp_name, 0o644)
        os.replace(temp_name, target)
    except BaseException:
        Path(temp_name).unlink(missing_ok=True)
        raise
    return artifact.artifact_id


# --- Run id and diff ---


def compute_run_id(payload: Mapping[str, Any]) -> str:
    """First 12 hex of the SHA-256 of ``payload`` (config, data hashes, outputs).

    Both the report and every artifact entry of a run carry it, which is what lets
    ``calibration-verify`` tie them together without a hash cycle.
    """
    return hashlib.sha256(compact_json(payload).encode("utf-8")).hexdigest()[:12]


_VOLATILE = {("evidence", "run_id"), ("evidence", "report")}


def _flatten(value: Any, prefix: tuple[str, ...] = ()) -> dict[tuple[str, ...], Any]:
    if isinstance(value, Mapping):
        flat: dict[tuple[str, ...], Any] = {}
        for key, child in value.items():
            flat.update(_flatten(child, (*prefix, str(key))))
        return flat if flat else {prefix: {}}
    return {prefix: value}


def diff_entries(
    old: Mapping[str, Any] | None, new: Mapping[str, Any], limit: int = 80
) -> list[str]:
    """Human-readable changes between two entries of one DP, without run ids.

    ``old`` is None for a DP the artifact did not have.
    """
    if old is None:
        return ["new decision point (no previous entry)"]
    before, after = _flatten(old), _flatten(new)
    lines: list[str] = []
    for path in sorted(set(before) | set(after)):
        if path in _VOLATILE:
            continue
        name = ".".join(path)
        if path not in before:
            lines.append(f"+ {name} = {after[path]!r}")
        elif path not in after:
            lines.append(f"- {name} (was {before[path]!r})")
        elif before[path] != after[path]:
            lines.append(f"~ {name}: {before[path]!r} -> {after[path]!r}")
    if len(lines) > limit:
        hidden = len(lines) - limit
        lines = [*lines[:limit], f"... and {hidden} more changed fields"]
    return lines
