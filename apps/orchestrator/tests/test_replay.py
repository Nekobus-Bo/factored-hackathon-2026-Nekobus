"""Unit tests for Replay recorder and player (ADR-0001).

Verifies:
- Deterministic key computation:
  sha256(model_id, prompt_version, masked_messages, tool_schema_hash)
- Key changes on prompt_version modification
- Key changes on masked messages modification
- Key changes on tool schema modification
- Replay persistence under eval/replay/<key>.json
- Replay miss handling (fail)
"""

from pathlib import Path

from orchestrator.llm.replay import (
    RecordedResponse,
    ReplayManager,
    compute_recording_key,
    compute_tool_schema_hash,
)


def test_compute_recording_key_deterministic() -> None:
    msgs = [{"role": "user", "content": "I lost my [CARD_1]"}]
    tools = [{"type": "function", "function": {"name": "card.block"}}]
    tool_hash = compute_tool_schema_hash(tools)

    k1 = compute_recording_key("model-a", "v1.0", msgs, tool_hash)
    k2 = compute_recording_key("model-a", "v1.0", msgs, tool_hash)
    assert k1 == k2

    # Different prompt version -> different key
    k_v2 = compute_recording_key("model-a", "v2.0", msgs, tool_hash)
    assert k1 != k_v2

    # Different model -> different key
    k_diff_model = compute_recording_key("model-b", "v1.0", msgs, tool_hash)
    assert k1 != k_diff_model

    # Different messages -> different key
    msgs_diff = [{"role": "user", "content": "Hello world"}]
    k_diff_msgs = compute_recording_key("model-a", "v1.0", msgs_diff, tool_hash)
    assert k1 != k_diff_msgs

    # Different tools -> different key
    tools_diff = [{"type": "function", "function": {"name": "handoff.create"}}]
    k_diff_tools = compute_recording_key(
        "model-a", "v1.0", msgs, compute_tool_schema_hash(tools_diff)
    )
    assert k1 != k_diff_tools


def test_replay_manager_save_and_load(tmp_path: Path) -> None:
    mgr = ReplayManager(replay_dir=tmp_path, mode="replay", record=True)
    msgs = [{"role": "user", "content": "block [CARD_1]"}]
    resp = RecordedResponse(
        content="I will block your card now.",
        tool_calls=[{"name": "card.block", "args": {}}],
        usage={"prompt_tokens": 10, "completion_tokens": 8, "total_tokens": 18},
        cost=0.0001,
    )

    key = compute_recording_key("model-x", "v1", msgs, "")
    saved = mgr.save_recording(
        key=key,
        model_id="model-x",
        prompt_version="v1",
        masked_messages=msgs,
        tool_schema_hash="",
        response=resp,
    )
    assert saved.key == key
    assert (tmp_path / f"{key}.json").is_file()

    loaded = mgr.load_recording(key)
    assert loaded is not None
    assert loaded.key == key
    assert loaded.response.content == "I will block your card now."
    assert loaded.response.tool_calls == [{"name": "card.block", "args": {}}]
    assert loaded.response.usage["total_tokens"] == 18


def test_replay_miss_behavior(tmp_path: Path) -> None:
    mgr = ReplayManager(
        replay_dir=tmp_path, mode="replay", record=False, replay_on_miss="fail"
    )
    non_existent_key = "0123456789abcdef" * 4

    assert mgr.load_recording(non_existent_key) is None
