import { useState, type FormEvent, type Ref } from "react";
import { MAX_MESSAGE_LENGTH } from "../../machines/chat.machine";
import type { Dictionary } from "../../i18n";
import { Icon } from "../ui/Icon";

export interface ComposerProps {
  dict: Dictionary;
  /** No message can be sent now: one is in flight, a rate limit is running, or the conversation is gone. */
  sendDisabled: boolean;
  onSend: (text: string) => void;
  inputRef?: Ref<HTMLInputElement>;
}

export function Composer({ dict, sendDisabled, onSend, inputRef }: ComposerProps) {
  const [draft, setDraft] = useState("");
  const empty = draft.trim() === "";

  const submit = (event: FormEvent) => {
    event.preventDefault();
    if (sendDisabled || empty) return;
    onSend(draft);
    setDraft("");
  };

  return (
    <form className="pb-chat__composer" onSubmit={submit}>
      <label className="pb-field">
        <span className="pb-sr">{dict.chat.composerLabel}</span>
        <input
          ref={inputRef}
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
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
