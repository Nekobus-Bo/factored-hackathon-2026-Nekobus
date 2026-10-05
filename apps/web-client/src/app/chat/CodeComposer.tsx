// The composer while a one-time code is pending: instead of the free text area, a field that takes only the six
// digits of the code, drawn as six boxes (the system's `pb-code__d`, the digit cell of the inbox, in its code type),
// with a visible label over them and "Cancelar" beside them, and no send button. One real input lies over the boxes,
// transparent: paste, `autocomplete="one-time-code"`, the numeric keyboard and the screen reader work on it, a click
// on any box is a click on it, and the boxes only show its value. The sixth digit sends the code by itself, once,
// through the chat's own send (so the demo script and the "Código: ••••••" mask work as for any message); while
// the turn is in flight the field is off. When the code ran out the field gives way to "Pedir otro código", a
// fixed message the assistant answers: the client cannot call tools. Props only, so it renders on the server in
// the tests.

import { useEffect, useId, useRef, useState, type FormEvent, type ReactNode, type Ref } from "react";
import type { Dictionary } from "../../i18n";
import { CODE_LENGTH, codeFieldChange, type CodeMode } from "../../machines/chat-model";
import { Icon } from "../ui/Icon";

export interface CodeComposerProps {
  dict: Dictionary;
  mode: Extract<CodeMode, { kind: "entry" | "expired" }>;
  /** A message is in flight, a rate limit runs or the conversation is gone: nothing can be sent now. */
  sendDisabled: boolean;
  /** The six digits, once. */
  onSend: (code: string) => void;
  onCancel: () => void;
  /** "Pedir otro código". */
  onRequestNew: () => void;
  /** Out of sight but mounted (the detective view in place of the chat). */
  hidden?: boolean;
  /** The code input, for the dock to give it the focus (reopening the chat, coming back from the detective view). */
  inputRef?: Ref<HTMLInputElement>;
  /** "Pedir otro código", for the same. */
  requestRef?: Ref<HTMLButtonElement>;
}

/** The six boxes of the field: one per digit typed, the next one to type in marked. The input is its child, over them. */
export function CodeCells({ digits, disabled, children }: { digits: string; disabled: boolean; children?: ReactNode }) {
  return (
    <div className="pb-code pb-code-entry__cells" data-disabled={disabled ? "" : undefined}>
      {Array.from({ length: CODE_LENGTH }, (_, index) => (
        <span
          key={index}
          className="pb-code__d pb-t-code pb-code-entry__cell"
          aria-hidden="true"
          data-active={!disabled && index === digits.length ? "true" : undefined}
        >
          {digits[index] ?? ""}
        </span>
      ))}
      {children}
    </div>
  );
}

export function CodeComposer({ dict, mode, sendDisabled, onSend, onCancel, onRequestNew, hidden = false, inputRef, requestRef }: CodeComposerProps) {
  const t = dict.chat.code;
  const [digits, setDigits] = useState("");
  const own = useRef<HTMLInputElement | null>(null);
  const requestOwn = useRef<HTMLButtonElement | null>(null);
  const formRef = useRef<HTMLFormElement>(null);
  const inputId = useId();
  const errorId = `${inputId}-error`;

  // The field takes the focus when the mode starts and again when a turn ends (a failed code leaves it empty, ready for the next).
  useEffect(() => {
    if (mode.kind !== "entry" || sendDisabled) return;
    // Not from the side panel or the page: only when the focus is nowhere or already in the chat.
    const active = document.activeElement;
    if (!active || active === document.body || formRef.current?.closest(".pb-chat")?.contains(active)) own.current?.focus();
  }, [mode.kind, sendDisabled]);

  // What was typed belongs to the code that was asked for: when the field gives way (the code expired, or it ended),
  // the digits go, so they cannot complete the next code.
  useEffect(() => {
    if (mode.kind !== "entry") setDigits("");
  }, [mode.kind]);

  // The code ran out: the field is gone from under the focus, and "Pedir otro código" takes it (only if the focus was
  // here or nowhere: a customer in the guide keeps theirs).
  useEffect(() => {
    if (mode.kind !== "expired") return;
    const active = document.activeElement;
    if (!active || active === document.body || formRef.current?.contains(active)) requestOwn.current?.focus();
  }, [mode.kind]);

  const change = (raw: string) => {
    const next = codeFieldChange(raw, sendDisabled);
    setDigits(next.digits);
    if (next.send !== null) onSend(next.send);
  };

  // The input is transparent and the box to type in is always the one after the last digit: the cursor stays at the end
  // whatever a click or an arrow tried, so what is edited is always what is seen.
  const keepAtEnd = (element: HTMLInputElement) => {
    const end = element.value.length;
    if (element.selectionStart !== end || element.selectionEnd !== end) element.setSelectionRange(end, end);
  };

  const cancel = (
    <button className="pb-btn pb-btn--ghost pb-code-entry__cancel" type="button" onClick={onCancel}>
      {t.cancel}
    </button>
  );

  return (
    <form ref={formRef} className="pb-chat__composer pb-code-entry" hidden={hidden} onSubmit={(event: FormEvent) => event.preventDefault()}>
      {mode.kind === "entry" ? (
        <>
          <div className="pb-code-entry__field">
            <label className="pb-t-label" htmlFor={inputId}>
              {t.label}
            </label>
            <CodeCells digits={digits} disabled={sendDisabled}>
              <input
                id={inputId}
                className="pb-code-entry__input"
                ref={(element) => {
                  own.current = element;
                  if (typeof inputRef === "function") inputRef(element);
                  else if (inputRef) (inputRef as { current: HTMLInputElement | null }).current = element;
                }}
                type="text"
                inputMode="numeric"
                autoComplete="one-time-code"
                pattern="[0-9]*"
                // no maxLength: a pasted "588 820" is seven characters and the filter, not the browser, keeps the digits
                value={digits}
                disabled={sendDisabled}
                aria-invalid={mode.failed ? true : undefined}
                aria-describedby={mode.failed ? errorId : undefined}
                data-code-field
                onChange={(event) => change(event.target.value)}
                onSelect={(event) => keepAtEnd(event.currentTarget)}
                onKeyDown={(event) => {
                  if (["ArrowLeft", "ArrowRight", "ArrowUp", "ArrowDown", "Home", "End"].includes(event.key)) event.preventDefault();
                }}
              />
            </CodeCells>
          </div>
          {cancel}
          {mode.failed && (
            <p className="pb-unsent pb-code-entry__error" id={errorId} role="alert">
              <span>
                <Icon name="warning" />
                {t.failed}
              </span>
            </p>
          )}
        </>
      ) : (
        <>
          <p className="pb-code-entry__note" role="status">
            {t.expired}
          </p>
          <button
            ref={(element) => {
              requestOwn.current = element;
              if (typeof requestRef === "function") requestRef(element);
              else if (requestRef) (requestRef as { current: HTMLButtonElement | null }).current = element;
            }}
            className="pb-btn pb-btn--secondary"
            type="button"
            disabled={sendDisabled}
            data-code-new
            onClick={onRequestNew}
          >
            {t.requestNew}
          </button>
          {cancel}
        </>
      )}
    </form>
  );
}
