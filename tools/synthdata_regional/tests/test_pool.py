"""Pooling the regional splits (no real data: fake locales in a temp dir)."""

import json
from types import SimpleNamespace

import pytest

from tools.synthdata_regional.pool import pooled_split


def _write(path, rows):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")


def _locale(tmp_path, code, stem, rows_by_split, with_locale):
    out = tmp_path / stem
    splits = {
        "train": f"{stem}.train.jsonl",
        "validation": f"{stem}.validation.jsonl",
        "test": f"{stem}.test.provisional.jsonl",
    }
    for split, n in rows_by_split.items():
        rows = [
            {
                "id": f"{stem}-{split}-{i}",
                "text": "t",
                "lang": code[:2],
                "intent": "greeting",
                "split": split,
                **({"locale": code} if with_locale else {}),
            }
            for i in range(n)
        ]
        _write(out / splits[split], rows)
    return SimpleNamespace(out_dir=out, splits=splits)


@pytest.fixture
def locales(tmp_path):
    return {
        "pt-BR": _locale(
            tmp_path,
            "pt-BR",
            "pt",
            {"train": 2, "validation": 1, "test": 1},
            with_locale=False,
        ),
        "es-MX": _locale(
            tmp_path,
            "es-MX",
            "mx",
            {"train": 3, "validation": 1, "test": 1},
            with_locale=True,
        ),
    }


@pytest.fixture
def template_dir(tmp_path):
    d = tmp_path / "synthetic"
    for name in ("decision.validation.jsonl", "decision.test.provisional.jsonl"):
        _write(
            d / name,
            [
                {
                    "id": f"{lang}-{name}",
                    "text": "t",
                    "lang": lang,
                    "intent": "greeting",
                    "split": "validation",
                }
                for lang in ("es", "pt", "en")
            ],
        )
    return d


def test_pt_rows_get_their_locale_and_order_is_kept(locales, template_dir):
    rows = pooled_split("train", locales, template_dir)
    assert [r["locale"] for r in rows] == ["pt-BR"] * 2 + ["es-MX"] * 3
    assert rows[0]["id"] == "pt-train-0"


def test_english_template_rows_join_validation_and_test_only(locales, template_dir):
    assert all(r["lang"] != "en" for r in pooled_split("train", locales, template_dir))
    for split in ("validation", "test"):
        rows = pooled_split(split, locales, template_dir)
        english = [r for r in rows if r["lang"] == "en"]
        assert len(english) == 1 and "locale" not in english[0]
        assert not [r for r in rows if r["lang"] in ("es", "pt") and "locale" not in r]


def test_a_missing_split_names_the_command_that_builds_it(locales, template_dir):
    (locales["es-MX"].out_dir / locales["es-MX"].splits["test"]).unlink()
    with pytest.raises(
        FileNotFoundError, match="make build-test-regional LOCALE=es-MX"
    ):
        pooled_split("test", locales, template_dir)
