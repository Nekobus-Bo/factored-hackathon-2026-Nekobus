"""Can a scenario's initial_state be satisfied on the proposed system?

Setup goes only through banking-core's admin API (policy, fixture reset) and a
FaultInjector; the runner never writes to the database. When a precondition
cannot be established, the scenario is reported as not runnable with the
reason instead of being forced.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from contracts.tools import TOOL_CATALOG

from evalrunner.models import Scenario
from evalrunner.systems.evidence import (
    SCENARIO_CUSTOMERS,
    EvidenceSource,
    PolicySnapshot,
    fixture_customer_id,
)
from evalrunner.systems.faults import FaultInjector

NO_OTP_CHANNEL = "NONE"
SEED_POLICY_MODE = "flag"
ADMIN_MISSING = "admin API missing"


@dataclass
class Assessment:
    scenario_id: str
    blockers: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    @property
    def runnable(self) -> bool:
        return not self.blockers


def replay_recordings(replay_dir: Path) -> int:
    return len(list(replay_dir.glob("*.json"))) if replay_dir.is_dir() else 0


def scenario_policy(scenario: Scenario) -> PolicySnapshot:
    wanted = scenario.initial_state.policy.amount_threshold_minor
    return PolicySnapshot(
        amount_mode=scenario.initial_state.policy.mode,
        thresholds_minor=wanted if isinstance(wanted, dict) else {},
    )


def policy_differences(current: PolicySnapshot, wanted: PolicySnapshot) -> list[str]:
    diffs: list[str] = []
    if current.amount_mode != wanted.amount_mode:
        diffs.append(
            f"policy mode is '{current.amount_mode}', scenario needs "
            f"'{wanted.amount_mode}'"
        )
    differing = {
        cur
        for cur, amount in wanted.thresholds_minor.items()
        if current.thresholds_minor.get(cur) != amount
    }
    if wanted.thresholds_minor:
        # The admin API replaces the whole map, so a currency the scenario leaves
        # out (an unmapped currency, on purpose) must be gone from the policy.
        differing |= set(current.thresholds_minor) - set(wanted.thresholds_minor)
    if differing:
        diffs.append(f"policy thresholds differ for {sorted(differing)}")
    return diffs


def scenario_tool_policy(scenario: Scenario) -> dict[str, list[str]]:
    """States the scenario wants for the tools it names; the rest stay on the seed.

    An enabled tool gets its catalog states, which never exceed the code floor;
    a disabled one gets none.
    """
    setup = scenario.initial_state.tool_policy
    if setup is None:
        return {}
    wanted = {name: [] for name in setup.disabled}
    for name in setup.enabled:
        wanted[name] = sorted(s.value for s in TOOL_CATALOG[name].permitted_states)
    return wanted


def tool_policy_differences(
    current: dict[str, list[str]], wanted: dict[str, list[str]]
) -> list[str]:
    return [
        f"tool policy for '{name}' is {sorted(current.get(name, []))}, "
        f"scenario needs {sorted(states)}"
        for name, states in sorted(wanted.items())
        if sorted(current.get(name, [])) != sorted(states)
    ]


def assess(
    scenario: Scenario,
    evidence: EvidenceSource | None,
    replay_dir: Path,
    admin_available: bool,
    faults: FaultInjector,
    tool_policy_verified: bool = False,
    live_llm: bool = False,
) -> Assessment:
    """Static checks always; live checks when an evidence source is given.

    With `admin_available`, differences the admin API can fix (policy, card
    fixtures) are notes, not blockers: the run applies them, then re-verifies.
    The tool policy is not in the evidence source: it is set and read back
    through the admin API, so `tool_policy_verified` tells the re-verification
    that the caller already did. With `live_llm` the orchestrator calls its
    model live, so no replay recording is needed (and none is made).
    """
    result = Assessment(scenario_id=scenario.id)
    state = scenario.initial_state

    if state.fault != "none" and not faults.supports(state.fault):
        result.blockers.append(
            f"fault '{state.fault}' needs compose-level fault injection"
        )

    if state.customer not in SCENARIO_CUSTOMERS:
        result.blockers.append(f"customer '{state.customer}' has no seed fixture")

    if state.tool_policy is not None and not (admin_available or tool_policy_verified):
        result.blockers.append(f"tool policy needs setup ({ADMIN_MISSING})")

    if evidence is None:
        if state.policy.mode != SEED_POLICY_MODE and not admin_available:
            result.blockers.append(
                f"policy mode '{state.policy.mode}' needs setup ({ADMIN_MISSING})"
            )
        result.notes.append("policy, customer and card state not verified (offline)")
    else:
        _assess_live(result, scenario, evidence, admin_available)

    exp = scenario.expected
    needs_handoff_payload = bool(exp.handoff_must_include) or (
        exp.handoff_priority is not None
    )
    if needs_handoff_payload and (evidence is None or not evidence.has_handoff_table()):
        result.blockers.append(
            "handoff priority/context evidence needs ops.handoff (not present)"
        )

    if live_llm:
        result.notes.append("LLM live: this run cannot be replayed")
    elif replay_recordings(replay_dir) == 0:
        result.blockers.append(f"no replay recordings in {replay_dir}")
    else:
        result.notes.append("a missing recording is reported at run time")

    return result


def _assess_live(
    result: Assessment,
    scenario: Scenario,
    evidence: EvidenceSource,
    admin_available: bool,
) -> None:
    state = scenario.initial_state
    fixture = SCENARIO_CUSTOMERS.get(state.customer)

    if fixture is not None:
        customer_id = fixture_customer_id(fixture)
        if not evidence.customer_exists(customer_id):
            result.blockers.append(f"fixture customer '{fixture}' is not seeded")
        else:
            channel = evidence.customer_otp_channel(customer_id)
            has_channel = channel is not None and channel != NO_OTP_CHANNEL
            if has_channel != (state.registered_otp_channel == "present"):
                result.blockers.append(
                    f"OTP channel is '{channel}', scenario needs "
                    f"'{state.registered_otp_channel}'"
                )
            own = [c for c in evidence.cards() if c.customer_id == customer_id]
            wrong = sorted({c.status for c in own if c.status != state.card_status})
            if wrong:
                message = f"card status {wrong} != '{state.card_status}'"
                if admin_available:
                    result.notes.append(f"{message}: reset via admin API")
                else:
                    result.blockers.append(f"{message} ({ADMIN_MISSING}: no reset)")

    policy = evidence.active_policy()
    if policy is None:
        result.blockers.append("no active row in config.policy_config")
        return
    for diff in policy_differences(policy, scenario_policy(scenario)):
        if admin_available:
            result.notes.append(f"{diff}: set via admin API")
        else:
            result.blockers.append(f"{diff} ({ADMIN_MISSING})")
