// "¿Te ayudó el asistente?": one line after the handoff block, between hairlines, with two equal buttons
// (neither filled: it is a question, not a nudge). Answering swaps the question for the thanks; ignoring it
// costs nothing. The answer goes to banking-core, which keeps one per handoff (ADR-0017).

import type { Dictionary } from "../../i18n";
import type { FeedbackState } from "../../machines/chat.machine";
import { Icon } from "../ui/Icon";

const QUESTION_ID = "feedback-question";

export function FeedbackLine({ dict, state, onAnswer }: { dict: Dictionary; state: FeedbackState; onAnswer: (helpful: boolean) => void }) {
  const t = dict.chat.feedback;
  if (state === "sent") {
    return (
      <div className="pb-rate" role="status">
        <p className="pb-rate__done">
          <Icon name="check" />
          {t.thanks}
        </p>
      </div>
    );
  }
  const sending = state === "sending";
  return (
    <div className="pb-rate" role="group" aria-labelledby={QUESTION_ID}>
      <div className="pb-rate__ask">
        <span id={QUESTION_ID} role={state === "failed" ? "alert" : undefined}>
          {state === "failed" ? `${t.failed} ${t.question}` : t.question}
        </span>
        <span className="pb-rate__btns">
          <button className="pb-rate__btn" type="button" aria-label={t.yesLabel} disabled={sending} onClick={() => onAnswer(true)}>
            <span className="pb-cut pb-rate__face">{t.yes}</span>
          </button>
          <button className="pb-rate__btn" type="button" aria-label={t.noLabel} disabled={sending} onClick={() => onAnswer(false)}>
            <span className="pb-cut pb-rate__face">{t.no}</span>
          </button>
        </span>
      </div>
    </div>
  );
}
