"""The cached list of decision points the encoder serves, and the settings wiring.

Asking for an id the encoder does not know fails the whole analyze call, so the
listing decides what is asked; it is fetched lazily, refreshed on a timer, kept
when a refresh fails, and never fetched once per turn against a dead encoder.
"""

from pathlib import Path
from typing import Any

import pytest
import yaml
from contracts import DecisionPointsResponse
from orchestrator.config import Settings
from orchestrator.conversation.decisions.catalog import ServedCatalog
from orchestrator.conversation.decisions.config import DEFAULT_EFFECTS_FILE
from orchestrator.conversation.decisions.effects import DecisionRuntime
from orchestrator.conversation.decisions.records import Mode
from orchestrator.encoder_client import EncoderUnavailableError

from .fake_encoder import LEGACY_SEED, listing


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


class Source:
    """Something with `async decision_points()` that can be told to fail."""

    def __init__(self, *bodies: dict[str, Any]) -> None:
        self.bodies = list(bodies)
        self.calls = 0
        self.down = False

    async def decision_points(self) -> DecisionPointsResponse:
        self.calls += 1
        if self.down:
            raise EncoderUnavailableError("encoder unreachable: ConnectError")
        body = self.bodies[min(self.calls, len(self.bodies)) - 1]
        return DecisionPointsResponse.model_validate(body)


def catalog(clock: Clock) -> ServedCatalog:
    return ServedCatalog(refresh_seconds=300, retry_seconds=15, clock=clock)


async def test_the_listing_is_fetched_once_and_then_served_from_the_cache() -> None:
    clock, source = Clock(), Source(listing())
    cache = catalog(clock)

    first = await cache.get(source)
    clock.now += 299
    second = await cache.get(source)

    assert first is second
    assert source.calls == 1


async def test_the_listing_is_refreshed_when_it_is_due() -> None:
    clock, source = Clock(), Source(listing(), LEGACY_SEED)
    cache = catalog(clock)
    await cache.get(source)

    clock.now += 301
    refreshed = await cache.get(source)

    assert source.calls == 2
    assert refreshed is not None and refreshed.source == "legacy_seed"


async def test_a_dead_encoder_is_asked_once_per_retry_interval_not_once_per_turn() -> (
    None
):
    clock, source = Clock(), Source(listing())
    source.down = True
    cache = catalog(clock)

    assert await cache.get(source) is None
    assert await cache.get(source) is None
    clock.now += 14
    assert await cache.get(source) is None
    assert source.calls == 1

    clock.now += 2  # 16 s since the failure
    source.down = False
    assert await cache.get(source) is not None
    assert source.calls == 2


async def test_a_failed_refresh_keeps_the_last_good_listing() -> None:
    clock, source = Clock(), Source(listing())
    cache = catalog(clock)
    good = await cache.get(source)
    clock.now += 400
    source.down = True

    assert await cache.get(source) is good


async def test_invalidating_fetches_again_on_the_next_get() -> None:
    clock, source = Clock(), Source(listing(), LEGACY_SEED)
    cache = catalog(clock)
    await cache.get(source)

    cache.invalidate()
    refreshed = await cache.get(source)

    assert source.calls == 2
    assert refreshed is not None and refreshed.source == "legacy_seed"


async def test_invalidating_also_clears_the_retry_backoff() -> None:
    clock, source = Clock(), Source(listing())
    source.down = True
    cache = catalog(clock)
    await cache.get(source)
    source.down = False

    cache.invalidate()

    assert await cache.get(source) is not None


async def test_a_source_without_a_listing_gives_nothing() -> None:
    assert await catalog(Clock()).get(object()) is None
    assert await catalog(Clock()).get(None) is None


async def test_an_unexpected_failure_is_logged_by_type_only(
    caplog: pytest.LogCaptureFixture,
) -> None:
    class Exploding:
        async def decision_points(self) -> None:
            raise RuntimeError("the body said: hola soy Ana Pérez")

    with caplog.at_level("WARNING"):
        assert await catalog(Clock()).get(Exploding()) is None

    assert "RuntimeError" in caplog.text
    assert "Ana" not in caplog.text


# ---------------------------------------------------------------- the settings


def test_the_runtime_reads_the_shipped_file_by_default() -> None:
    runtime = DecisionRuntime.from_settings(Settings(_env_file=None))

    assert runtime.config.source == str(DEFAULT_EFFECTS_FILE)
    assert {dp.mode for dp in runtime.config.decision_points.values()} == {Mode.SHADOW}


def test_the_mode_override_of_the_environment_reaches_the_runtime() -> None:
    settings = Settings(
        _env_file=None,
        DECISION_POINTS_MODES="confirm_gate=enforce, block_reason=off",
    )

    runtime = DecisionRuntime.from_settings(settings)

    assert runtime.config.modes()["confirm_gate"] == "enforce"
    assert runtime.config.modes()["block_reason"] == "off"
    assert "block_reason" not in [dp.id for dp in runtime.config.active()]


def test_the_effects_file_can_be_moved_with_the_environment(tmp_path: Path) -> None:
    document = yaml.safe_load(DEFAULT_EFFECTS_FILE.read_text("utf-8"))
    document["decision_points"] = {
        "turn_intent": document["decision_points"]["turn_intent"]
    }
    path = tmp_path / "effects.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")

    runtime = DecisionRuntime.from_settings(
        Settings(_env_file=None, DECISION_EFFECTS_FILE=str(path))
    )

    assert list(runtime.config.decision_points) == ["turn_intent"]
