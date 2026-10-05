// The next line of the running demo script as something to do: its card (the line as written, not a button) and, beside
// it, two icon buttons of the same kind: send it as written, and "Copiar al chat" to edit it in the composer first. One component for the two places that
// offer it, the guide's current step (`GuidePanel`) and the band over the composer (`NextBand`), so the disabled rules
// and the handlers are the same. The line is the script's own, in the script's language, and is never translated.

import { currentStep, getScript, type ScriptState } from "@pattern-blue/contracts";
import { useId } from "react";
import type { Dictionary } from "../../i18n";
import { Icon } from "../ui/Icon";

export interface NextLineProps {
  dict: Dictionary;
  /** The line, as the script wrote it. */
  text: string;
  /** The script's market: the language of the line. */
  locale: string;
  /** Nothing can be sent now: a message is in flight, a rate limit is running, or the conversation is gone. */
  disabled: boolean;
  /** A message waits for its retry. */
  awaitingRetry: boolean;
  /** Off because the assistant is answering or a rate limit runs: the send button shows the waiting clock (not for the other reasons). */
  waiting?: boolean;
  /** The code field is the composer in sight: a line cannot be copied into it. */
  codeFieldShown: boolean;
  onSend: (text: string) => void;
  onCopy: (text: string) => void;
  /** The band's smaller card: less padding, the line clamped to three lines with its full text in `title`. */
  compact?: boolean;
}

export function NextLine({ dict, text, locale, disabled, awaitingRetry, waiting = false, codeFieldShown, onSend, onCopy, compact = false }: NextLineProps) {
  const t = dict.chat.guide;
  const off = disabled || awaitingRetry;
  return (
    <div className="pb-guide__line">
      {/* The line itself: the outlined twin of the bubble it becomes. Not a button: the two actions are beside it. */}
      <p className={compact ? "pb-cut pb-say__card pb-say__card--compact" : "pb-cut pb-say__card"} title={compact ? text : undefined}>
        <span className="pb-say__text" lang={locale}>
          {text}
        </span>
      </p>
      <span className="pb-guide__actions">
        {/* Two buttons of the same kind (one primary per view, and it is the composer's send): send, then copy. */}
        <button
          className="pb-btn pb-btn--secondary pb-btn--icon pb-guide__send"
          type="button"
          data-say={text}
          aria-label={t.send}
          title={t.send}
          disabled={off}
          data-waiting={waiting ? "true" : undefined}
          aria-busy={waiting ? true : undefined}
          onClick={() => onSend(text)}
        >
          <Icon name={waiting ? "clock" : "send"} />
        </button>
        <button
          className="pb-btn pb-btn--secondary pb-btn--icon pb-guide__copy"
          type="button"
          data-copy={text}
          aria-label={t.copy}
          title={t.copy}
          disabled={off || codeFieldShown}
          onClick={() => onCopy(text)}
        >
          <Icon name="copy" />
        </button>
      </span>
    </div>
  );
}

/** The next line of a running script when it is a message (not the code step, not complete, not stopped), or null. */
export function nextMessageOf(script: ScriptState | null): { text: string; locale: string } | null {
  if (!script || script.status !== "running") return null;
  const step = currentStep(script);
  if (step?.kind !== "message") return null;
  return { text: step.text, locale: getScript(script.scriptId).locale };
}

export interface NextBandProps extends Omit<NextLineProps, "text" | "locale" | "compact" | "codeFieldShown"> {
  script: ScriptState | null;
}

/**
 * The suggested next line over the composer, for when the demo panel is not showing beside the chat (on a phone each
 * step is one tap, with no trip to the menu). It sits outside the log: it is not a message and the live region does not
 * announce it. The dock decides when it is drawn (the panel is not showing, the code field is not the composer).
 */
export function NextBand({ script, ...line }: NextBandProps) {
  const next = nextMessageOf(script);
  const titleId = useId();
  if (!next) return null;
  return (
    <div className="pb-say pb-say--next" role="group" aria-labelledby={titleId} data-script-band>
      <p className="pb-say__title" id={titleId}>
        {line.dict.chat.guide.next}
      </p>
      <NextLine {...line} text={next.text} locale={next.locale} codeFieldShown={false} compact />
    </div>
  );
}
