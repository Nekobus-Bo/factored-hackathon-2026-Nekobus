import tempfile
from pathlib import Path

import pytest
from calibrate.runner import run_decision_calibration, run_embedding_calibration


def test_runner_decision_smoke():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_file = run_decision_calibration(
            config_path="tools/calibrate/configs/decision.yaml",
            out_dir=tmpdir,
        )
        assert report_file.is_file()
        content = report_file.read_text(encoding="utf-8")
        assert "Decision Model Calibration Report" in content
        assert "tfidf_lr" in content


def test_runner_embedding_smoke():
    with tempfile.TemporaryDirectory() as tmpdir:
        report_file = run_embedding_calibration(
            config_path="tools/calibrate/configs/embedding.yaml",
            out_dir=tmpdir,
        )
        assert report_file.is_file()
        content = report_file.read_text(encoding="utf-8")
        assert "Embedding Model Calibration Report" in content
        assert "bm25" in content


def test_guard_fixture_output_raises_for_reports():
    import pytest
    from calibrate.runner import guard_fixture_output

    with pytest.raises(ValueError, match="Refusing to write fixture"):
        guard_fixture_output(
            data_paths=["tools/calibrate/fixtures/decision.jsonl"],
            out_dir="reports",
        )


def test_guard_fixture_output_allows_tmp():
    from calibrate.runner import guard_fixture_output

    # Non-reports destination should pass without error
    guard_fixture_output(
        data_paths=["tools/calibrate/fixtures/decision.jsonl"],
        out_dir="/tmp/calib",
    )


def test_guard_fixture_output_allows_tmp_reports():
    from calibrate.runner import guard_fixture_output

    # Destination like /tmp/reports/x outside the repo must be allowed
    guard_fixture_output(
        data_paths=["tools/calibrate/fixtures/decision.jsonl"],
        out_dir="/tmp/reports/custom_run",
    )


class _FakeHeavyAdapter:
    def __init__(self, mb: int) -> None:
        self.blob = bytearray(mb * 1024 * 1024)
        for i in range(0, len(self.blob), 4096):
            self.blob[i] = 1

    def predict(self, texts, candidate_intents=None, candidate_slots=None):
        from encoder.models import DecisionPrediction

        intent = candidate_intents[0] if candidate_intents else "unknown"
        return [
            DecisionPrediction(
                intent=intent,
                confidence=0.99,
                slots=[],
                probabilities={intent: 0.99},
            )
            for _ in texts
        ]


def test_unregistered_fake_heavy_adapter_fails():
    """Verify config with type fake_heavy fails with unknown adapter type."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cfg = Path(tmpdir) / "cfg.yaml"
        tmp_cfg.write_text(
            """
task: decision
mode: zeroshot
data_path: tools/calibrate/fixtures/decision.jsonl
p_min: 0.9
languages:
  - es
candidates:
  - name: heavy_candidate
    model_id: heavy_candidate
    type: fake_heavy
    alloc_mb: 200
""",
            encoding="utf-8",
        )
        with pytest.raises(ValueError, match="unknown adapter type"):
            run_decision_calibration(config_path=tmp_cfg, out_dir=tmpdir)


def test_fake_heavy_adapter_ram_measurement(monkeypatch):
    """Verify registered fake adapter allocating ~200 MB shows >= 150 MB."""
    import calibrate.runner as runner

    monkeypatch.setitem(
        runner.ADAPTER_REGISTRY,
        "fake_heavy",
        lambda cand: _FakeHeavyAdapter(int(cand.get("alloc_mb", 200))),
    )

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_cfg = Path(tmpdir) / "cfg.yaml"
        tmp_cfg.write_text(
            """
task: decision
mode: zeroshot
data_path: tools/calibrate/fixtures/decision.jsonl
p_min: 0.9
languages:
  - es
candidates:
  - name: heavy_candidate
    model_id: heavy_candidate
    type: fake_heavy
    alloc_mb: 200
""",
            encoding="utf-8",
        )
        report_file = run_decision_calibration(config_path=tmp_cfg, out_dir=tmpdir)
        content = report_file.read_text(encoding="utf-8")
        assert "RAM model+inference Δ (MB)" in content

        found = False
        for line in content.splitlines():
            if "heavy_candidate" in line:
                cols = [c.strip() for c in line.split("|")[1:-1]]
                ram_val = float(cols[-1])
                assert ram_val >= 150.0, f"Expected RAM >= 150 MB, got {ram_val} MB"
                found = True
        assert found, "heavy_candidate row not found in report"
