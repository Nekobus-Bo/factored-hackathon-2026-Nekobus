import { useState, type FormEvent, type KeyboardEvent, type Ref } from "react";
import { MAX_MESSAGE_LENGTH } from "../../machines/chat.machine";
import type { Dictionary } from "../../i18n";
import { Icon } from "../ui/Icon";

export interface ComposerProps {
  dict: Dictionary;
  /** No message can be sent now: one is in flight, a rate limit is running, or the conversation is gone. */
  sendDisabled: boolean;
  onSend: (text: string) => void;
  inputRef?: Ref<HTMLTextAreaElement>;
}

/** A text area that grows to four lines (the CSS caps it). Enter sends; Shift+Enter starts a new line. */
export function Composer({ dict, sendDisabled, onSend, inputRef }: ComposerProps) {
  const [draft, setDraft] = useState("");
  const empty = draft.trim() === "";

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
    <form className="pb-chat__composer" onSubmit={submit}>
      <label className="pb-field">
        <span className="pb-sr">{dict.chat.composerLabel}</span>
        <textarea
          ref={inputRef}
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
      >
        <Icon name="send" />
      </button>
    </form>
  );
}
