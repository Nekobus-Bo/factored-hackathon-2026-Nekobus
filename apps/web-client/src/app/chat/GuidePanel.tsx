// The demo guide (ScriptChoice): the content of the script tab of the demo panel at the left of the chat (the panel
// itself, with its tabs and the "Solo demo" tag, is `SidePanel`). It offers the team's six scripts and, once one
// is chosen, its next message. Props only, no machine, so it renders on the server in the tests exactly as it
// does in the page. Nothing here is inside the conversation: the click on an option is what sends.
//
// The scripts' own lines come from `@pattern-blue/contracts` and are shown as written, in the script's language:
// they are the test and are never translated. Everything else (labels, notes, hints) is the dictionary's.

import { currentStep, DEMO_SCRIPTS, getScript, type DemoScript, type DemoScriptId, type ScriptState } from "@pattern-blue/contracts";
import { useRef, type ReactNode, type Ref } from "react";
import { format, type Dictionary } from "../../i18n";
import { Icon } from "../ui/Icon";

export interface GuidePanelProps {
  dict: Dictionary;
  /** Where the customer stands in a script, or null: the six scripts are offered. */
  script: ScriptState | null;
  /** Nothing can be sent now: a message is in flight, a rate limit is running, or the conversation is gone. */
  disabled: boolean;
  /**
   * The six scripts are off: a message is in flight or a rate limit runs. Defaults to `disabled`; an expired
   * conversation disables the next line (nothing can be sent in it) but not the six (choosing one opens a new conversation).
   */
  chooseDisabled?: boolean;
  /** A message waits for its retry: the next line is off until it went, the six scripts are not. */
  awaitingRetry?: boolean;
  /** A script was chosen. */
  onPick: (id: DemoScriptId) => void;
  /** The next line of the running script was chosen. */
  onSend: (text: string) => void;
  /** "Cambiar de guion". */
  onReset: () => void;
  /** The title of the panel, for the dock to give it the focus when what had it goes away. */
  titleRef?: Ref<HTMLParagraphElement>;
}

/** What a script is called and what its note says, in the dictionary's language. */
function scriptText(dict: Dictionary, id: DemoScriptId): { label: string; note?: string; amount?: string } {
  return dict.chat.guide.scripts[id];
}

/** The first line of a script: always a message. */
function firstLine(script: DemoScript): string {
  const first = script.steps[0];
  return first?.kind === "message" ? first.text : "";
}

/** "Guardrail: umbral COP 2.000.000, handoff recomendado", with the amount in mono. */
function Note({ text, amount }: { text: string; amount: string }) {
  const [before = "", after = ""] = text.split("{amount}");
  return (
    <span className="pb-say__note">
      <Icon name="info" />
      <span>
        {before}
        <span className="pb-t-mono">{amount}</span>
        {after}
      </span>
    </span>
  );
}

/** The pointer at the code step: the names of the two actions are the chat's own, in bold. */
function CodeHint({ dict }: { dict: Dictionary }): ReactNode {
  const parts = dict.chat.guide.codeHint.split(/(\{open\}|\{reveal\})/);
  return parts.map((part, index) => {
    if (part === "{open}") return <b key={index}>{dict.chat.inbox.open}</b>;
    if (part === "{reveal}") return <b key={index}>{dict.chat.inbox.reveal}</b>;
    return part;
  });
}

/** "Paso n": the step the script is on (the last one once complete; where it stopped, when stopped). */
function progressOf(script: ScriptState, total: number): number {
  return script.status === "complete" ? total : Math.min(script.step + 1, total);
}

function MarketTag({ dict, locale }: { dict: Dictionary; locale: string }) {
  return (
    <span className="pb-tag">
      <span className="pb-sr">{dict.chat.guide.market} </span>
      {locale}
    </span>
  );
}

export function GuidePanel({ dict, script, disabled, chooseDisabled = disabled, awaitingRetry = false, onPick, onSend, onReset, titleRef: outerTitleRef }: GuidePanelProps) {
  const t = dict.chat.guide;
  const titleRef = useRef<HTMLParagraphElement | null>(null);
  const definition = script ? getScript(script.scriptId) : null;

  // "Cambiar de guion" takes its own button with it: the focus goes to the title, which stays.
  const reset = () => {
    onReset();
    titleRef.current?.focus();
  };

  return (
    <>
      <div className="pb-guide__body">
        <p
          className="pb-guide__title"
          ref={(element) => {
            titleRef.current = element;
            if (typeof outerTitleRef === "function") outerTitleRef(element);
            else if (outerTitleRef) (outerTitleRef as { current: HTMLParagraphElement | null }).current = element;
          }}
          tabIndex={-1}
        >
          {definition && script ? (
            <>
              {scriptText(dict, definition.id).label} <MarketTag dict={dict} locale={definition.locale} />
              <span className="pb-guide__progress">{format(t.progress, { n: progressOf(script, definition.steps.length), total: definition.steps.length })}</span>
            </>
          ) : (
            t.chooseTitle
          )}
        </p>
        {script && definition ? (
          <>
            <p className="pb-guide__hint">{script.status === "running" ? t.runningHint : script.status === "complete" ? t.completeHint : t.stoppedHint}</p>
            <ol className="pb-guide__steps">
              {definition.steps.map((step, index) => {
                const state = index < script.step ? "done" : currentStep(script) !== null && index === script.step ? "current" : "next";
                // A stopped script offers nothing: only what was sent stays, so the track ends where it stopped.
                if (script.status === "stopped" && state !== "done") return null;
                const code = step.kind === "code";
                const icon = state === "done" ? "check" : code ? "mail" : state === "current" ? "hex" : "chat";
                const label = state === "done" ? (code ? t.codeDone : t.sent) : state === "current" ? t.now : t.follows;
                return (
                  <li className="pb-guide__step" key={index} data-state={state}>
                    <div className="pb-guide__main">
                      <span className="pb-guide__label">
                        <Icon name={icon} />
                        {label}
                      </span>
                      {step.kind === "code" ? (
                        state === "done" ? null : (
                          <p className="pb-guide__card">
                            <CodeHint dict={dict} />
                          </p>
                        )
                      ) : state === "current" ? (
                        <button
                          className="pb-cut pb-say__opt"
                          type="button"
                          data-say={step.text}
                          disabled={disabled || awaitingRetry}
                          onClick={() => onSend(step.text)}
                        >
                          <span className="pb-say__body">
                            <span className="pb-say__text" lang={definition.locale}>
                              {step.text}
                            </span>
                          </span>
                          <span className="pb-say__side">
                            <span className="pb-say__go">
                              <Icon name="send" />
                            </span>
                          </span>
                        </button>
                      ) : state === "done" ? (
                        <p className="pb-guide__sent" lang={definition.locale}>
                          {step.text}
                        </p>
                      ) : (
                        <p className="pb-guide__card" lang={definition.locale}>
                          {step.text}
                        </p>
                      )}
                    </div>
                  </li>
                );
              })}
            </ol>
          </>
        ) : (
          <>
            <p className="pb-guide__hint">{t.chooseHint}</p>
            <ul className="pb-say__list">
              {DEMO_SCRIPTS.map((candidate) => {
                const text = scriptText(dict, candidate.id);
                const line = firstLine(candidate);
                return (
                  <li key={candidate.id}>
                    <button
                      className="pb-cut pb-say__opt"
                      type="button"
                      data-script={candidate.id}
                      data-say={line}
                      disabled={chooseDisabled}
                      onClick={() => onPick(candidate.id)}
                    >
                      <span className="pb-say__body">
                        <span className="pb-say__label">{text.label}</span>
                        <span className="pb-say__text" lang={candidate.locale} title={line}>
                          {line}
                        </span>
                        {text.note !== undefined && text.amount !== undefined ? <Note text={text.note} amount={text.amount} /> : null}
                      </span>
                      <span className="pb-say__side">
                        <MarketTag dict={dict} locale={candidate.locale} />
                        <span className="pb-say__go">
                          <Icon name="send" />
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          </>
        )}
      </div>
      {script ? (
        <div className="pb-guide__foot">
          <button className="pb-action" type="button" onClick={reset}>
            {t.change}
            <Icon name="arrow" />
          </button>
        </div>
      ) : null}
    </>
  );
}
