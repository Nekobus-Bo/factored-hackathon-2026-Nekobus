"""System prompt for the turn engine. No policy lives here (ADR-0002).

Bump PROMPT_VERSION on any change: it is part of the replay key, and a prompt
change needs `make eval` before and after (AGENTS.md).
"""

from orchestrator.conversation.models import Lang

PROMPT_VERSION = "turn-engine/3"

SYSTEM_PROMPT = (
    "You are the customer service assistant of a bank. You help customers "
    "through the tools you are given; banking-core decides whether a tool may "
    "run, and you relay its answer faithfully.\n"
    "- Customer data appears as placeholders such as [DOC_1], [OTP_1] or "
    "[CARD_1]. Pass them to tools exactly as written; never guess the values.\n"
    "- If a tool is refused, explain it plainly to the customer. Do not retry "
    "it with different arguments to get around the refusal.\n"
    "- If a tool answers CONFIRMATION_REQUIRED, ask the customer to confirm that "
    "action in one short question and do not call it again until they answer.\n"
    "- Never state that an action happened unless a tool result confirms it.\n"
    "- Reply in the customer's language (Spanish, Portuguese or English), "
    'as plain text or as JSON {"blocks": [{"type": "text", "text": ...}]}.'
)

# The `hint` effect (ADR-0001, ADR-0014): one system line after the prompt, only when
# the decision point is in `enforce`. It names a category, never a number or text,
# and says plainly that it is not an authorization.
HINT_TEMPLATE = (
    "Local intent classifier (advisory; banking-core decides what is allowed): "
    "the customer's latest message most likely means `{label}`."
)
HINT_UNCERTAIN = (
    "Local intent classifier (advisory; banking-core decides what is allowed): "
    "the intent of the customer's latest message is uncertain."
)

FALLBACK_MESSAGES: dict[Lang, str] = {
    "es": (
        "No pude completar tu solicitud en este momento. "
        "¿Puedes intentarlo de nuevo o pedir hablar con un agente?"
    ),
    "pt": (
        "Não consegui concluir sua solicitação agora. "
        "Pode tentar novamente ou pedir para falar com um atendente?"
    ),
    "en": (
        "I couldn't complete your request right now. "
        "Could you try again or ask to speak with an agent?"
    ),
}

REPHRASE_MESSAGES: dict[Lang, str] = {
    "es": (
        "No pude procesar tu mensaje de forma segura. "
        "¿Puedes escribirlo de nuevo con otras palabras?"
    ),
    "pt": (
        "Não consegui processar sua mensagem com segurança. "
        "Pode escrevê-la de novo com outras palavras?"
    ),
    "en": (
        "I couldn't process your message safely. "
        "Could you write it again in different words?"
    ),
}
