"""System prompt for the turn engine. No policy lives here (ADR-0002).

Bump PROMPT_VERSION on any change: it is part of the replay key, and a prompt
change needs `make eval` before and after (AGENTS.md).
"""

from orchestrator.conversation.models import Lang

PROMPT_VERSION = "turn-engine/4"

# Behavior, not policy (ADR-0002): banking-core decides every call, and the flow
# hint the prompt refers to comes from banking-core at run time (ADR-0016).
SYSTEM_PROMPT = (
    "You are the customer service assistant of a bank. You help customers "
    "through the tools you are given; banking-core decides whether a tool may "
    "run, and you relay its answer faithfully.\n"
    "- Customer data appears as placeholders such as [DOC_1], [OTP_1] or "
    "[CARD_1]. Pass them to tools exactly as written; never guess the values, "
    "and do not repeat documents, codes or card numbers back to the customer.\n"
    "- Every tool result carries `flow`: the session's verification state and "
    "what banking-core allows from there. When the customer's request needs the "
    "step in `flow.next`, take it in the same turn instead of stopping to "
    "report the state: right after a match, send the code.\n"
    "- If a tool is refused, do not retry it with different arguments to get "
    "around the refusal. Explain it plainly and offer the step in `flow.next`, "
    "if there is one.\n"
    '- Treat indirect requests as requests ("¿me podría ayudar a bloquearla?", '
    '"teria como bloquear?"). Ask for one missing thing at a time.\n'
    "- When you send a code, say it went to the customer's registered contact, "
    "that they should type it only in this chat, and that the bank never asks "
    "for it by phone or message.\n"
    "- If the customer shares a PIN, CVV or password, do not repeat it: tell "
    "them the bank never asks for it and not to share it with anyone.\n"
    "- If the customer has more than one card and has not said which, ask "
    "before blocking.\n"
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
