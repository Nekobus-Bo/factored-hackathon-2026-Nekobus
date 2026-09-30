"""Unit tests for the locale-aware regional dataset pipeline (no data files, no LLM)."""

import random
import re

import polars as pl
import pytest

from tools.synthdata_regional import register
from tools.synthdata_regional.build_test import load_templates
from tools.synthdata_regional.checks import check_pii, check_purity
from tools.synthdata_regional.fill import fill, placeholder_problem
from tools.synthdata_regional.locales import ES_AR, ES_MX, LOCALES, PLACEHOLDERS, PT_BR, document_profiles


@pytest.mark.parametrize("loc", list(LOCALES.values()), ids=list(LOCALES))
def test_fill_offsets_are_exact(loc):
    template = "Mi tarjeta {card_last4}: {currency}{amount} en {merchant} el {transaction_date}"
    for seed in range(30):
        text, slots = fill(loc, template, "request_dispute", random.Random(seed))
        assert "{" not in text
        for slot in slots:
            assert text[slot["start"]:slot["end"]] == slot["value"]


@pytest.mark.parametrize("loc,template,surface", [
    (ES_AR, "mi DNI es {document_number}", "dni"),
    (ES_AR, "mi CUIT {document_number}", "cuit"),
    (ES_MX, "mi CURP es {document_number}", "curp"),
    (ES_MX, "mi RFC: {document_number}", "rfc"),
    (PT_BR, "meu cpf é {document_number}", "cpf"),
])
def test_named_document_gets_a_matching_number(loc, template, surface):
    numbers = {d["number"] for d in document_profiles(loc) if d["surface"].lower() == surface}
    for seed in range(20):
        _, slots = fill(loc, template, "provide_identity_data", random.Random(seed))
        assert slots[0]["value"] in numbers


@pytest.mark.parametrize("loc", [ES_MX, ES_AR], ids=["es-MX", "es-AR"])
def test_document_type_and_number_come_as_a_pair(loc):
    pairs = {(d["surface"], d["number"]) for d in document_profiles(loc)}
    for seed in range(30):
        _, slots = fill(loc, "{document_type} {document_number}", "provide_identity_data", random.Random(seed))
        values = {s["type"]: s for s in slots}
        assert (values["document_type"]["value"], values["document_number"]["value"]) in pairs
        assert values["document_type"]["normalized"] in {"NATIONAL_ID", "PASSPORT", "FOREIGN_ID", "TAX_ID"}


@pytest.mark.parametrize("loc", [ES_MX, ES_AR], ids=["es-MX", "es-AR"])
def test_relative_date_never_follows_an_article(loc):
    for seed in range(40):
        text, _ = fill(loc, "vi un cargo del {transaction_date}", "report_unrecognized_charge", random.Random(seed))
        assert not re.search(r"\bdel (hoy|ayer|antier|anteayer|el)\b", text)


def test_placeholder_problems():
    assert placeholder_problem("mi código es {otp_code}", "provide_otp_code") == ""
    assert placeholder_problem("mi código es 123", "provide_otp_code") == "required placeholder missing"
    assert placeholder_problem("hola {full_name}", "greeting") == "unknown or disallowed placeholder"
    assert placeholder_problem("saldo {card_last4", "check_balance") == "stray brace"
    assert set(PLACEHOLDERS) <= {"report_unrecognized_charge", "request_dispute", "report_lost_card", "report_stolen_card",
                                 "request_card_block", "report_suspicious_activity", "provide_identity_data",
                                 "provide_otp_code", "check_balance", "check_recent_transactions"}


@pytest.mark.parametrize("loc", [ES_MX, ES_AR], ids=["es-MX", "es-AR"])
def test_fictitious_pii_would_be_caught_outside_slots(loc):
    """Every document number and phone the locale fills in matches its own PII pattern,
    so the same value written without a slot is rejected by check_pii."""
    pii = re.compile(loc.pii_rx)
    for value in [d["number"] for d in loc.document_profiles] + loc.fillers["phone"]:
        assert pii.search(f"mi dato es {value} ok"), value


def test_check_pii_ignores_slots_and_flags_the_rest():
    df = pl.DataFrame([
        {"id": "ok", "text": "mi DNI es 30.123.456", "slots": [{"type": "document_number", "value": "30.123.456", "start": 10, "end": 20}]},
        {"id": "leak", "text": "mi DNI es 30.123.456", "slots": []},
    ])
    assert check_pii(df, ES_AR) == ["leak: PII-like text outside slots"]


def test_regional_purity_separates_the_two_countries():
    rioplatense = "che, ¿me podés decir cuánta plata tengo?"
    mexicano = "oye, ¿me puedes checar el saldo ahorita?"
    neutral = "quiero saber mi saldo, por favor"
    assert re.search(ES_MX.foreign_markers, rioplatense)
    assert re.search(ES_AR.foreign_markers, mexicano)
    assert not re.search(ES_MX.foreign_markers, neutral)
    assert not re.search(ES_AR.foreign_markers, neutral)
    df = pl.DataFrame({"text": [neutral] * 99 + [rioplatense], "file_split": ["train"] * 100})
    assert check_purity(df, ES_MX)[0] == []  # 1% is still allowed
    df = pl.DataFrame({"text": [neutral] * 98 + [rioplatense] * 2, "file_split": ["train"] * 100})
    assert check_purity(df, ES_MX)[0]


def test_register_profile_and_distance():
    uniform = ["Me cobraron un cargo que no reconozco, ¿me pueden ayudar a revisarlo por favor?"] * 20
    varied = ["no me deja entrar", "pésima app!!", "Hace una semana que intento pagar la luz y la app se cierra sola cada vez que llego al final 😡",
              "saldo", "no anda nada desde la actualización, ya la desinstalé dos veces"] * 4
    u, v = register.profile(uniform, ES_AR), register.profile(varied, ES_AR)
    assert u["words_cv"] == 0 and v["words_cv"] > 0.5
    assert u["ends_request"] == 1.0 and v["ends_request"] == 0.0
    assert register.distance(u, u) == 0
    assert register.distance(u, v) > 0


def test_slang_shares():
    shares = register.slang_shares(["qué quilombo", "todo bien", "un quilombo total", "che, hola"], ES_AR)
    assert shares["quilombo"] == 0.5 and shares["che"] == 0.25
    assert list(shares)[0] == "quilombo"


def test_load_templates_reads_both_formats(tmp_path):
    (tmp_path / "test_templates.1.txt").write_text(
        "@greeting short\nhola\nbuenas\n@out_of_scope long oos_app\nla app no abre desde ayer y ya la reinstalé\n", encoding="utf-8")
    (tmp_path / "test_templates.2.tsv").write_text("confirm\tshort\t\tsí\n", encoding="utf-8")
    rows = load_templates(tmp_path)
    assert [(r["intent"], r["length"], r["topic"]) for r in rows] == [
        ("greeting", "short", ""), ("greeting", "short", ""), ("out_of_scope", "long", "oos_app"), ("confirm", "short", "")]
    (tmp_path / "test_templates.3.txt").write_text("hola sin cabecera\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_templates(tmp_path)
