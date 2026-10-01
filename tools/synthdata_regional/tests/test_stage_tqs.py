"""Staging the tuquejasuma.com threads for es-CO (no real data: a tiny parquet in a temp dir)."""

import polars as pl
import pytest

from tools.synthdata_regional.stage_tqs import clean, consumer_turns, scrub_names


@pytest.mark.parametrize("text,expected", [
    ("Soy carlos mario giraldo duque, actualmente manejo", "Soy [nombre], actualmente manejo"),
    ("mi nombre es dilan arteta. hola", "mi nombre es [nombre]. hola"),
    ("soy jorge villarreal titular de la cuenta", "soy [nombre] titular de la cuenta"),
    ("hablé con la asesora maria lopez y nada", "hablé con la asesora [nombre] y nada"),
    ("soy un cliente constante", "soy un cliente constante"),
    ("mi nombre y cédula para", "mi nombre y cédula para"),
    ("Soy venezolano y no", "Soy venezolano y no"),
    ("la asesora me dijo que", "la asesora me dijo que"),
])
def test_scrub_names(text, expected):
    assert scrub_names(text) == expected


def test_clean_drops_the_vote_counter_and_unescapes_entities():
    assert clean("2 ¡Sumados!\nPor parte del banco") == "Por parte del banco"
    assert clean("Atrápalo Colombia 1 ¡Sumado! Como es posible &amp; ya") == "Como es posible & ya"
    assert clean("No me llegó la plata") == "No me llegó la plata"


def test_consumer_turns_keeps_bank_consumer_text_only(tmp_path):
    snap = tmp_path / "snapshot_co_1000"
    snap.mkdir()
    pl.DataFrame({
        "thread_id": ["co-1", "co-1", "co-2", "co-3"],
        "turn": [0, 1, 0, 0],
        "role": ["consumer", "agent", "consumer", "consumer"],
        "author": ["", "Ana B", "", ""],
        "text": ["3 ¡Sumados! Hice una transferencia y no llegó", "Lamentamos lo ocurrido con su caso", "No llegó el pedido de tenis", "ok"],
        "company_name": ["Bancolombia", "Bancolombia", "Adidas Colombia", "DaviPlata"],
    }).write_parquet(snap / "tqs_co_dataset.parquet")
    frame = consumer_turns("co", tmp_path)
    assert frame["ask"].to_list() == ["Hice una transferencia y no llegó"]  # agent, non-bank and too-short rows dropped
    assert set(frame.columns) == {"company", "source", "ask", "thread_id", "turn"}
    assert frame["source"][0] == "tqs_thread"
