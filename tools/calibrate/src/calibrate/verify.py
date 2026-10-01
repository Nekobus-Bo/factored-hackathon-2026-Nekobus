"""``make calibration-verify``: a static check of the committed calibration artifact.

It trains nothing, loads no model and needs no network, so it is cheap enough for CI.
It answers one question: *is this artifact still the one its evidence describes?*

Per artifact:

* it validates against the encoder's own schema, and its ``artifact_id`` matches its
  content (a hand edit fails here);
* the JSON Schema published next to it is what the code generates (no drift);
* every backend's pin holds: a ``tfidf_lr`` backend's train file exists, hashes to the
  pinned SHA-256 and gives the stated ``model_id``; a hub model has a full commit and
  a weights hash (their bytes cannot be checked offline, and the service verifies them
  at startup);

per decision point:

* status is ``calibrated`` or ``infeasible`` (a seed never ships), and a ``calibrated``
  DP decides in at least one language, with a calibrator wherever it has a tau;
* its evidence names a report that exists, contains the run id, and embeds the DP's
  artifact fragment verbatim (so the report is the evidence for *these* numbers);
* the data files its evidence names still hash to what it recorded;

and, when ``apps/orchestrator/config/decision_effects.yaml`` exists, that every label
and DP the effects file names is one the artifact serves (ADR-0012, B.4).

The check for the calibration config's hash is a warning, not an error: a config may
gain a DP for someone else's calibration without invalidating the rest.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from encoder.decision_points import (
    DEFAULT_ARTIFACT_PATH,
    ArtifactError,
    DecisionPointsArtifact,
    artifact_json_schema,
    load_artifact,
    view_labels,
)
from encoder.pinning import is_commit
from encoder.registry import tfidf_model_id

from calibrate.artifact import fragment_of, fragment_text

SCHEMA_FILE = "packages/encoder/calibration/decision_points.schema.json"
DEFAULT_EFFECTS_PATH = "apps/orchestrator/config/decision_effects.yaml"
_SPLITS = ("train", "validation", "test")


@dataclass
class VerifyResult:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _resolve(root: Path, name: str) -> Path:
    path = Path(name)
    return path if path.is_absolute() else root / path


def verify(
    artifact_path: Path | str | None = None,
    *,
    repo_root: Path | str = ".",
    effects_path: Path | str | None = None,
    schema_path: Path | str | None = None,
) -> VerifyResult:
    """Run every static check; never raises for a finding, only for a bug."""
    root = Path(repo_root)
    result = VerifyResult()
    path = _resolve(root, str(artifact_path or DEFAULT_ARTIFACT_PATH))

    try:
        artifact = load_artifact(path)
    except ArtifactError as exc:
        result.errors.append(str(exc))
        return result
    raw = json.loads(path.read_text(encoding="utf-8"))
    result.notes.append(
        f"artifact {artifact.artifact_id}: {len(artifact.decision_points)} decision "
        f"points, {len(artifact.backends)} backends ({path})"
    )

    _check_schema_file(result, _resolve(root, str(schema_path or SCHEMA_FILE)))
    for backend_id, backend in artifact.backends.items():
        _check_backend(result, root, backend_id, backend)
    for dp_id in artifact.decision_points:
        _check_decision_point(result, root, artifact, raw, dp_id)

    effects = _resolve(root, str(effects_path or DEFAULT_EFFECTS_PATH))
    if effects.is_file():
        _check_effects(result, effects, artifact)
    else:
        result.notes.append(
            f"effects file {effects} not present: effects/artifact cross-check skipped"
        )
    return result


# --- Schema and backends ---


def _check_schema_file(result: VerifyResult, schema: Path) -> None:
    if not schema.is_file():
        result.warnings.append(f"JSON Schema {schema} not found: drift not checked")
        return
    try:
        published = json.loads(schema.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.errors.append(f"{schema}: not valid JSON ({exc.msg})")
        return
    if published != artifact_json_schema():
        result.errors.append(
            f"{schema} is out of date with encoder.decision_points; regenerate it with "
            "`uv run python -m encoder.decision_points "
            "packages/encoder/calibration/decision_points.schema.json`"
        )


def _check_backend(
    result: VerifyResult, root: Path, backend_id: str, backend: Any
) -> None:
    label = f"backend '{backend_id}'"
    if backend.kind == "tfidf_lr":
        if backend.train is None:
            result.errors.append(f"{label}: tfidf_lr needs a train block")
            return
        train = _resolve(root, backend.train.path)
        if not train.is_file():
            result.errors.append(f"{label}: train data {backend.train.path} not found")
            return
        actual = file_sha256(train)
        if actual != backend.train.sha256:
            result.errors.append(
                f"{label}: {backend.train.path} hashes to {actual[:12]}..., the "
                f"artifact pins {backend.train.sha256[:12]}...; the train data changed "
                "since calibration. Recalibrate (make calibrate TASK=decision-points)"
            )
            return
        expected = tfidf_model_id(actual, backend.train.label_map)
        if backend.model_id != expected:
            result.errors.append(
                f"{label}: model_id {backend.model_id!r} should be {expected!r}"
            )
        return
    if backend.kind == "llm_sidecar":
        result.errors.append(
            f"{label}: pending: llm_sidecar is not implemented (ADR-0012)"
        )
        return
    if backend.kind == "hf_seqcls":
        _check_hf_seqcls(result, root, label, backend)
        return
    # Hub models: only the shape of the pin is checkable offline.
    if not is_commit(backend.revision):
        result.errors.append(
            f"{label}: revision must be a full 40-hex commit (a branch is not a pin)"
        )
    if backend.weights_sha256 is None:
        result.errors.append(f"{label}: weights_sha256 is missing")
    result.notes.append(
        f"{label}: {backend.kind} weights are verified by the service at startup"
    )


def _check_hf_seqcls(
    result: VerifyResult, root: Path, label: str, backend: Any
) -> None:
    """A trained directory (ADR-0014): the pins must be well formed; when the
    directory is here (a dev machine, the image), its manifest must match them."""
    from encoder.registry import hf_seqcls_model_id
    from encoder.weights import ManifestError, verify_manifest

    model = backend.params.get("model")
    if not isinstance(model, str) or not model:
        result.errors.append(f"{label}: params.model must name the model directory")
        return
    if backend.weights_sha256 is None or not backend.revision:
        result.errors.append(f"{label}: needs weights_sha256 and a revision label")
        return
    directory = _resolve(root, model)
    if not directory.is_dir():
        result.warnings.append(
            f"{label}: {model} is not here (it ships in the encoder image, "
            "ENCODER_WEIGHTS_IMAGE); pins checked by the service at startup"
        )
        return
    try:
        manifest = verify_manifest(directory)
    except ManifestError as exc:
        result.errors.append(f"{label}: {exc}")
        return
    if manifest.revision_label() != backend.revision:
        result.errors.append(
            f"{label}: revision {backend.revision!r}, the directory's manifest gives "
            f"{manifest.revision_label()!r}"
        )
    if manifest.files["model.safetensors"] != backend.weights_sha256:
        result.errors.append(f"{label}: weights_sha256 differs from {model}")
    expected = hf_seqcls_model_id(manifest.name, manifest.files["model.safetensors"])
    if backend.model_id != expected:
        result.errors.append(f"{label}: model_id should be {expected!r}")


# Data that is not versioned (ADR-0014): absent on CI and clean machines by design.
_UNVERSIONED = ("data/staging/", "data/raw/", "data/curated/")


# --- Decision points ---


def _check_decision_point(
    result: VerifyResult,
    root: Path,
    artifact: DecisionPointsArtifact,
    raw: Mapping[str, Any],
    dp_id: str,
) -> None:
    label = f"decision point '{dp_id}'"
    dp = artifact.decision_points[dp_id]
    evidence = dp.evidence

    if dp.status == "uncalibrated_seed":
        result.errors.append(
            f"{label}: status uncalibrated_seed does not belong in a committed "
            "artifact; calibrate it"
        )
    if dp.status == "calibrated":
        languages = _decided_languages(dp.thresholds)
        if not languages:
            result.errors.append(
                f"{label}: status is calibrated but no language has a threshold; "
                "it should be infeasible"
            )
        if dp.calibrator.kind != "none":
            for lang in languages:
                if lang != "*" and lang not in dp.calibrator.by_lang:
                    if "*" not in dp.calibrator.by_lang:
                        result.errors.append(
                            f"{label}: language '{lang}' has a threshold but no "
                            "calibrator; the service would abstain there"
                        )

    run_id = evidence.get("run_id")
    report_name = evidence.get("report")
    if not run_id or not report_name:
        result.errors.append(f"{label}: evidence needs a run_id and a report")
    else:
        _check_report(result, root, artifact, raw, dp_id, str(run_id), str(report_name))

    _check_data(result, root, dp_id, evidence)
    if evidence.get("certified") is not True:
        result.notes.append(f"{label}: not certified (see its report)")


def _decided_languages(thresholds: Mapping[str, Any]) -> list[str]:
    languages = []
    for lang, entry in thresholds.items():
        if isinstance(entry, dict):
            if any(tau is not None for tau in entry.values()):
                languages.append(lang)
        elif entry is not None:
            languages.append(lang)
    return languages


def _check_report(
    result: VerifyResult,
    root: Path,
    artifact: DecisionPointsArtifact,
    raw: Mapping[str, Any],
    dp_id: str,
    run_id: str,
    report_name: str,
) -> None:
    label = f"decision point '{dp_id}'"
    report = _resolve(root, report_name)
    if not report.is_file():
        result.errors.append(f"{label}: report {report_name} not found")
        return
    text = report.read_text(encoding="utf-8")
    if run_id not in text:
        result.errors.append(
            f"{label}: run id {run_id} does not appear in {report_name}"
        )
    embedded = fragment_text(fragment_of(raw, dp_id))
    if embedded not in text:
        result.errors.append(
            f"{label}: {report_name} does not embed this entry's artifact fragment "
            "verbatim; the report is not the evidence for these numbers"
        )


def _check_data(
    result: VerifyResult, root: Path, dp_id: str, evidence: Mapping[str, Any]
) -> None:
    label = f"decision point '{dp_id}'"
    data = evidence.get("data")
    if not isinstance(data, Mapping):
        result.errors.append(f"{label}: evidence records no data hashes")
        return
    for split in _SPLITS:
        block = data.get(split)
        if not isinstance(block, Mapping) or not block.get("path"):
            result.errors.append(f"{label}: evidence.data.{split} needs a path")
            continue
        file = _resolve(root, str(block["path"]))
        if not file.is_file():
            if str(block["path"]).startswith(_UNVERSIONED):
                result.warnings.append(
                    f"{label}: {split} data {block['path']} is not versioned and not "
                    "here; its hash is recorded, not checked"
                )
            else:
                result.errors.append(f"{label}: {split} data {block['path']} not found")
        elif file_sha256(file) != block.get("sha256"):
            result.errors.append(
                f"{label}: {split} data {block['path']} changed since calibration "
                "(SHA-256 differs); recalibrate"
            )
    config = evidence.get("config")
    if isinstance(config, Mapping) and config.get("path"):
        file = _resolve(root, str(config["path"]))
        if not file.is_file():
            result.warnings.append(f"{label}: config {config['path']} not found")
        elif file_sha256(file) != config.get("sha256"):
            result.warnings.append(
                f"{label}: config {config['path']} changed since this decision point "
                "was calibrated"
            )


# --- Effects file (B.4) ---


def _check_effects(
    result: VerifyResult, effects: Path, artifact: DecisionPointsArtifact
) -> None:
    try:
        loaded = yaml.safe_load(effects.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        result.errors.append(f"{effects}: not valid YAML ({exc})")
        return
    points = loaded.get("decision_points") if isinstance(loaded, dict) else None
    if not isinstance(points, dict):
        result.errors.append(f"{effects}: needs a decision_points mapping")
        return
    served = {
        dp_id: set(view_labels(dp)) for dp_id, dp in artifact.decision_points.items()
    }
    checked = 0
    for dp_id, block in points.items():
        where = f"{effects.name}: '{dp_id}'"
        if dp_id not in served:
            result.errors.append(f"{where} is not a decision point of the artifact")
            continue
        checked += 1
        if not isinstance(block, dict):
            continue
        dp = artifact.decision_points[dp_id]
        if block.get("mode") == "enforce" and (
            not dp.enabled or dp.status != "calibrated"
        ):
            result.errors.append(
                f"{where} is in enforce but the artifact has it "
                f"{'disabled' if not dp.enabled else dp.status}"
            )
        params = block.get("params")
        if not isinstance(params, dict):
            continue
        for key in ("consent_labels", "revoke_labels"):
            _need_labels(result, where, f"params.{key}", params.get(key), served[dp_id])
        request = params.get("explicit_request")
        if isinstance(request, dict):
            other = request.get("dp")
            if other not in served:
                result.errors.append(
                    f"{where} params.explicit_request.dp names '{other}', which the "
                    "artifact does not have"
                )
            else:
                _need_labels(
                    result,
                    where,
                    "params.explicit_request.labels",
                    request.get("labels"),
                    served[other],
                )
        ledger = params.get("ledger")
        if isinstance(ledger, dict):
            _need_labels(
                result, where, "params.ledger.order", ledger.get("order"), served[dp_id]
            )
        for target in params.get("targets") or []:
            if isinstance(target, dict) and isinstance(target.get("map"), dict):
                _need_labels(
                    result,
                    where,
                    f"params.targets[{target.get('tool')}].map",
                    list(target["map"]),
                    served[dp_id],
                )
    result.notes.append(
        f"effects file {effects}: {checked} decision points cross-checked"
    )


def _need_labels(
    result: VerifyResult, where: str, field_name: str, value: Any, served: set[str]
) -> None:
    if value is None:
        return
    if not isinstance(value, list):
        result.errors.append(f"{where} {field_name} must be a list")
        return
    unknown = sorted(str(v) for v in value if v not in served)
    if unknown:
        result.errors.append(
            f"{where} {field_name} names {unknown}, not labels of that decision point "
            f"({sorted(served)})"
        )


# --- Command line ---


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="calibration-verify",
        description="Static check of the calibration artifact (ADR-0012)",
    )
    parser.add_argument(
        "--artifact",
        default=None,
        help=f"artifact file (default {DEFAULT_ARTIFACT_PATH})",
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="directory that paths in the artifact hang from",
    )
    parser.add_argument(
        "--effects", default=None, help="decision_effects.yaml to cross-check"
    )
    args = parser.parse_args(argv)

    result = verify(args.artifact, repo_root=args.repo_root, effects_path=args.effects)
    for note in result.notes:
        print(f"  note: {note}")
    for warning in result.warnings:
        print(f"  WARNING: {warning}", file=sys.stderr)
    for error in result.errors:
        print(f"  ERROR: {error}", file=sys.stderr)
    if result.ok:
        print("calibration-verify: OK")
        return 0
    print(f"calibration-verify: FAILED ({len(result.errors)} errors)", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
