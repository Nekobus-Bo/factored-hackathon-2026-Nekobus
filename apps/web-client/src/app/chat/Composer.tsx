import { useImperativeHandle, useLayoutEffect, useRef, useState, type FormEvent, type KeyboardEvent, type Ref } from "react";
import { MAX_MESSAGE_LENGTH } from "../../machines/chat.machine";
import type { Dictionary } from "../../i18n";
import { Icon } from "../ui/Icon";

export interface ComposerProps {
  dict: Dictionary;
  /** No message can be sent now: one is in flight, a rate limit is running, or the conversation is gone. */
  sendDisabled: boolean;
  /** The send button is off because the assistant is answering (or a rate limit runs): its glyph is the waiting clock. */
  waiting?: boolean;
  onSend: (text: string) => void;
  inputRef?: Ref<HTMLTextAreaElement>;
  /** Fills the draft from outside (the demo guide's "Copiar al chat"). */
  handleRef?: Ref<ComposerHandle>;
  /** Out of sight but still mounted, so the draft survives (the demo panel takes the chat's place). */
  hidden?: boolean;
}

export interface ComposerHandle {
  /** Replaces the draft with `text`, puts the focus in the text area with the caret at the end, and sends nothing. */
  fill: (text: string) => void;
}

/** A text area that grows to four lines (the CSS caps it). Enter sends; Shift+Enter starts a new line. */
export function Composer({ dict, sendDisabled, waiting = false, onSend, inputRef, handleRef, hidden = false }: ComposerProps) {
  const [draft, setDraft] = useState("");
  const empty = draft.trim() === "";
  const area = useRef<HTMLTextAreaElement | null>(null);
  // The draft is this component's state: a fill sets it and asks for the focus, which the layout effect gives once the
  // new value is in the text area (set before, the caret would stay where it was) and the area is shown (a hidden one
  // cannot take the focus), all in the commit of the click that asked.
  const [fillRequest, setFillRequest] = useState(0);
  useImperativeHandle(
    handleRef,
    () => ({
      fill: (text) => {
        setDraft(text);
        setFillRequest((count) => count + 1);
      },
    }),
    [],
  );
  useLayoutEffect(() => {
    const element = area.current;
    if (fillRequest === 0 || !element) return;
    element.focus();
    element.setSelectionRange(element.value.length, element.value.length);
  }, [fillRequest]);

  const send = () => {
    if (sendDisabled || empty) return;
    onSend(draft);
    setDraft("");
  };

  const submit = (event: FormEvent) => {
    event.preventDefault();
    send();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Not while an input method is composing a character: its Enter confirms the character.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return;
    event.preventDefault();
    send();
  };

  return (
    <form className="pb-chat__composer" hidden={hidden} onSubmit={submit}>
      <label className="pb-field">
        <span className="pb-sr">{dict.chat.composerLabel}</span>
        <textarea
          ref={(element) => {
            area.current = element;
            if (typeof inputRef === "function") inputRef(element);
            else if (inputRef) (inputRef as { current: HTMLTextAreaElement | null }).current = element;
          }}
          rows={1}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          onKeyDown={onKeyDown}
          placeholder={dict.chat.placeholder}
          autoComplete="off"
          enterKeyHint="send"
          maxLength={MAX_MESSAGE_LENGTH}
        />
      </label>
      <button
        className="pb-btn pb-btn--primary pb-btn--icon"
        type="submit"
        aria-label={dict.chat.send}
        disabled={sendDisabled || empty}
        data-waiting={waiting ? "true" : undefined}
        aria-busy={waiting ? true : undefined}
      >
        <Icon name={waiting ? "clock" : "send"} />
      </button>
    </form>
  );
}
