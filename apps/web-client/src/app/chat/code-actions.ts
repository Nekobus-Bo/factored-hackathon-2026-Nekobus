// What the code field's buttons do to the chat machine. Apart from the component so a test can run it without a DOM.

import type { Lang, Locale } from "@pattern-blue/contracts";
import { dictionaries } from "../../i18n";
import { conversationLang, type Entry } from "../../machines/chat-model";
import type { Actors } from "../actors";

/**
 * "Pedir otro código": a fixed message of the customer, in the language of the conversation (the customer's last
 * message, else the page's), because the client cannot call tools: the assistant is who resends the code. It goes
 * through the chat's own send, flagged as the chat's own request so a demo script waiting at its code step stays there.
 */
export function requestNewCode({ chat }: Pick<Actors, "chat">, entries: readonly Entry[], pageLang: Lang, locale: Locale | null): void {
  const lang = conversationLang(entries, pageLang);
  chat.send({ type: "SEND", text: dictionaries[lang].chat.code.requestMessage, lang, locale, codeRequest: true });
}
