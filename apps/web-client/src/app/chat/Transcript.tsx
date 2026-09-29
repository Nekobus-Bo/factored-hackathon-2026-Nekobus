// The log: one component per entry of the transcript. Props only, no machine, so it renders on the server
// in the tests exactly as it does in the page.

import type { Lang } from "@pattern-blue/contracts";
import { dictionaries, type Dictionary } from "../../i18n";
import { formatClock, type Entry } from "../../machines/chat-model";
import { Icon } from "../ui/Icon";
import { Blocks, MessageText } from "./Blocks";

export interface TranscriptProps {
  entries: readonly Entry[];
  /** The language of the page. */
  lang: Lang;
  /** A failed message that can be retried from the log itself (after a rate limit). */
  retryEntryId?: string | null;
  onRetry?: () => void;
}

export function Transcript({ entries, lang, retryEntryId = null, onRetry }: TranscriptProps) {
  const dict = dictionaries[lang];
  return (
    <>
      {entries.map((entry) => (
        <EntryView key={entry.id} entry={entry} lang={lang} dict={dict} canRetry={entry.id === retryEntryId} onRetry={onRetry} />
      ))}
    </>
  );
}

function EntryView({
  entry,
  lang,
  dict,
  canRetry,
  onRetry,
}: {
  entry: Entry;
  lang: Lang;
  dict: Dictionary;
  canRetry: boolean;
  onRetry?: () => void;
}) {
  switch (entry.kind) {
    case "customer": {
      const failed = entry.status === "failed";
      return (
        <div
          className="pb-msg pb-msg--customer"
          data-status={failed ? "failed" : undefined}
          lang={entry.lang === lang ? undefined : entry.lang}
        >
          <span className="pb-msg__meta">
            {dict.chat.roles.customer} · {formatClock(entry.at, entry.lang)}
            {failed && (
              <>
                {" · "}
                <Icon name="warning" />
                {dict.chat.notSent}
              </>
            )}
          </span>
          <MessageText text={entry.text} />
          {failed && canRetry && onRetry && (
            <button className="pb-action chat-inline-action" type="button" onClick={onRetry}>
              {dict.chat.retry}
              <Icon name="retry" />
            </button>
          )}
        </div>
      );
    }
    case "assistant":
      return <Blocks blocks={entry.blocks} turnLang={entry.lang} lang={lang} at={entry.at} />;
    case "agent":
      return (
        <div className="pb-msg pb-msg--agent">
          <span className="pb-msg__meta">
            <Icon name="user" />
            {dict.chat.roles.agent} · {formatClock(entry.at, lang)}
          </span>
          <MessageText text={entry.text} />
        </div>
      );
    case "system":
      return entry.code === "takeover" ? (
        <div className="pb-sys" data-tone="joined">
          <span className="pb-sys__text">
            <Icon name="user" />
            {dict.chat.takeoverStatus}
          </span>
        </div>
      ) : (
        <div className="pb-sys">
          <span className="pb-sys__text">
            <Icon name="clock" />
            {dict.chat.codeExpired}
          </span>
        </div>
      );
  }
}
