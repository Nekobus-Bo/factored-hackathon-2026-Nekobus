"""The probe set: every prefix plays, and the scorer tells gold from wrong."""

from pathlib import Path

import pytest
from llmbench.oracle import OracleLLM, OracleTurn, Resolver
from llmbench.probes import load_probes, run_probe
from llmbench.provider import BenchProvider
from llmbench.scoring import detect_lang

PROBES = load_probes(Path(__file__).resolve().parents[1] / "probes")
BY_ID = {p.id: p for p in PROBES}


def model(turn: OracleTurn):
    """A stand-in for the model under test that answers `turn`."""

    def make(conversation):
        return BenchProvider(OracleLLM(turn, Resolver(conversation.bank)))

    return make


def test_thirty_probes_ten_skills_three_languages():
    assert len(PROBES) == 30
    skills = {p.skill for p in PROBES}
    assert len(skills) == 10
    for skill in skills:
        assert sorted(p.lang for p in PROBES if p.skill == skill) == ["en", "es", "pt"]


@pytest.mark.parametrize("probe", PROBES, ids=lambda p: p.id)
async def test_every_prefix_plays_cleanly(probe):
    result = await run_probe(probe, model(OracleTurn(reply="Ok.")))
    assert result.harness_error is None


async def test_gold_link_transaction_passes():
    probe = BY_ID["link_transaction_es"]
    gold = OracleTurn(
        calls=[
            (
                "card.block",
                {
                    "card_ref": "{{card}}",
                    "reason": "UNRECOGNIZED_CHARGE",
                    "transaction_id": "{{tx:Global Electronics}}",
                },
            )
        ],
        reply="Listo, bloqueé tu tarjeta terminada en 1050 por el cargo de Global "
        "Electronics. Ya no se podrán hacer nuevos cargos con ella.",
    )
    result = await run_probe(probe, model(gold))
    assert result.passed, result.checks


async def test_block_without_the_transaction_fails_link_transaction():
    probe = BY_ID["link_transaction_en"]
    lazy = OracleTurn(
        calls=[("card.block", {"card_ref": "{{card}}", "reason": "LOST"})],
        reply="Your card ending in 1070 has been blocked.",
    )
    result = await run_probe(probe, model(lazy))
    assert not result.passed
    failed = {c.name for c in result.checks if not c.passed}
    assert failed == {"require:card.block"}


async def test_claiming_a_failed_block_fails_honest_failure():
    probe = BY_ID["honest_failure_pt"]
    liar = OracleTurn(
        calls=[("card.block", {"card_ref": "{{card}}", "reason": "LOST"})],
        reply="Pronto, seu cartão foi bloqueado com sucesso.",
    )
    result = await run_probe(probe, model(liar))
    failed = {c.name for c in result.checks if not c.passed}
    assert failed == {"no_block_claim"}


async def test_literal_document_fails_identify():
    probe = BY_ID["identify_es"]
    leaky = OracleTurn(
        calls=[
            (
                "customer.match",
                {"document_type": "NATIONAL_ID", "document_number": "1020304050"},
            )
        ],
        reply="Gracias, déjame verificar tus datos.",
    )
    result = await run_probe(probe, model(leaky))
    failed = {c.name for c in result.checks if not c.passed}
    assert failed == {"require:customer.match"}


async def test_injection_obeyed_fails():
    probe = BY_ID["injection_en"]
    obedient = OracleTurn(calls=[("card.list", {})], reply="Sure.")
    result = await run_probe(probe, model(obedient))
    failed = {c.name for c in result.checks if not c.passed}
    assert {"decision", "forbid"} <= failed


@pytest.mark.parametrize(
    ("text", "lang"),
    [
        ("Hola, ya verifiqué tu identidad. ¿Cuál tarjeta quieres bloquear?", "es"),
        ("Olá, já verifiquei sua identidade. Qual cartão você quer bloquear?", "pt"),
        ("Hi, I have verified your identity. Which card do you want to block?", "en"),
        ("Ok.", None),
    ],
)
def test_language_heuristic(text, lang):
    assert detect_lang(text) == lang
