"""Test-only TurnHandler. Lives in tests/ so src/ can never import it."""

import asyncio

from orchestrator.chat.handler import TurnOutcome
from orchestrator.privacy.masking import RegexMasker
from orchestrator.session.models import ConversationState

RECEIPT_BLOCK = {
    "type": "receipt",
    "receipt": {
        "action": "card.block",
        "target_masked": "card_ab12cd34",
        "state_before": "ACTIVE",
        "state_after": "BLOCKED",
        "verified_at": "2026-09-27T12:00:00Z",
        "audit_id": "aud_0001abcd",
    },
}


class FakeTurnHandler:
    """Masks like the engine would, then replies with `reply` (may echo PII).

    `gate` holds the turn open so a test can fire a concurrent request.
    """

    def __init__(
        self,
        reply: str = "Recibido: {user}",
        gate: asyncio.Event | None = None,
        fail: bool = False,
    ) -> None:
        self.reply = reply
        self.gate = gate
        self.fail = fail
        self.started = asyncio.Event()
        self.calls: list[tuple[str, str]] = []
        self.masker = RegexMasker()

    async def handle_turn(
        self, conversation: ConversationState, user_text: str
    ) -> TurnOutcome:
        self.calls.append((conversation.banking_session_id, user_text))
        self.started.set()
        if self.gate is not None:
            await self.gate.wait()
        if self.fail:
            raise RuntimeError("engine exploded")
        masked = self.masker.mask(user_text, state=conversation.placeholder_map)
        conversation.placeholder_map.update(masked.mapping)
        conversation.llm_history.append({"role": "user", "content": masked.masked_text})
        return TurnOutcome(
            blocks=[
                {"type": "text", "text": self.reply.format(user=user_text)},
                RECEIPT_BLOCK,
            ],
            metadata={"turn": len(self.calls)},
        )
