// What a click in the demo guide does to the two machines. Apart from the dock so a test can run it without a DOM.

import { currentStep, getScript, type DemoScriptId, type Lang, type Locale, type ScriptState } from "@pattern-blue/contracts";
import type { Actors } from "../actors";

/**
 * A script was chosen: the page moves to the script's market (its language comes with it) and the chat opens a
 * new conversation with the script's first line. The chat takes the language and the market from the script
 * itself, never from what the page showed a moment ago: the two sends do not depend on their order.
 */
export function startGuideScript({ app, chat }: Actors, id: DemoScriptId): void {
  app.send({ type: "LOCALE.SET", locale: getScript(id).locale });
  chat.send({ type: "SCRIPT.START", scriptId: id });
}

/** The running script's next line, as written, in the script's language (the conversation already has its market). */
export function sendGuideLine({ chat }: Pick<Actors, "chat">, script: ScriptState, text: string): void {
  const { lang, locale } = getScript(script.scriptId);
  chat.send({ type: "SEND", text, lang, locale });
}

/**
 * What the composer's send does. The running script's next line, typed or copied there and sent unchanged (the machine's own
 * rule: equal after trim), goes as a click on its card would, in the script's language and market; the page may have been
 * switched meanwhile, and the script's line is not in the page's language. Any other text goes as the page's.
 */
export function sendTyped({ chat }: Pick<Actors, "chat">, script: ScriptState | null, text: string, page: { lang: Lang; locale: Locale | null }): void {
  const step = script && script.status === "running" ? currentStep(script) : null;
  if (script && step?.kind === "message" && step.text === text.trim()) {
    sendGuideLine({ chat }, script, text);
    return;
  }
  chat.send({ type: "SEND", text, lang: page.lang, locale: page.locale });
}
