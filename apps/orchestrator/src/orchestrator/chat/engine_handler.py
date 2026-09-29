"""Adapter from the stateful turn engine to the chat handler contract."""

from orchestrator.chat.handler import TurnOutcome
from orchestrator.conversation import ConversationContext, TurnEngine
from orchestrator.session.models import ConversationState


class EngineTurnHandler:
    """Run engine turns against the server-side conversation state."""

    def __init__(self, engine: TurnEngine) -> None:
        self.engine = engine

    async def handle_turn(
        self,
        conversation: ConversationState,
        user_text: str,
        turn_id: str | None = None,
    ) -> TurnOutcome:
        context = ConversationContext(
            session_id=conversation.banking_session_id,
            language=conversation.language,
            history=conversation.llm_history,
            placeholder_map=conversation.placeholder_map,
            decisions=conversation.decisions,
            human_takeover=conversation.takeover.active,
        )
        result = await self.engine.run_turn(
            context, user_text, lang=conversation.language, turn_id=turn_id
        )

        conversation.llm_history = context.history
        conversation.placeholder_map = context.placeholder_map
        conversation.decisions = context.decisions
        return TurnOutcome(
            blocks=[block.model_dump(mode="json") for block in result.blocks],
            metadata=result.metadata.model_dump(mode="json"),
            eval=result.eval if self.engine.collect_eval else None,
        )
