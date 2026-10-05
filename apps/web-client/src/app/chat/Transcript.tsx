// The log: one component per entry of the transcript. Props only, no machine, so it renders on the server
// in the tests exactly as it does in the page.

import type { Lang } from "@pattern-blue/contracts";
import type { ReactNode } from "react";
import { dictionaries, type Dictionary } from "../../i18n";
import { formatClock, isHandoff, isOtpSendReceipt, lastEntryWith, type Entry } from "../../machines/chat-model";
import { Icon } from "../ui/Icon";
import { Blocks, MessageText, Sender } from "./Blocks";
import { TraceOpen } from "./TracePanel";

/** The message the API did not accept just now, and what the line under it says and offers. */
export interface PendingFailure {
  entryId: string;
  /** "Reintentar" resends it (503, or a rate limit that has run its course). */
  retry: boolean;
  /** Why, when it is worth saying: the assistant is not available. A rate limit has its own strip. */
  reason: string | null;
}

export interface TranscriptProps {
  entries: readonly Entry[];
  /** The language of the page. */
  lang: Lang;
  failure?: PendingFailure | null;
  onRetry?: () => void;
  /** Goes inside the newest `otp.send` receipt while its code is live: the countdown and the inbox action. */
  otpFoot?: ReactNode;
  /** Goes right after the newest handoff block: the feedback line. */
  afterHandoff?: ReactNode;
  /** The environment offers detective mode: each reply with a trace gets its control (ADR-0019). */
  detective?: boolean;
  /** A reply's control was picked: the detective view shows that turn. */
  onOpenTrace?: (entryId: string) => void;
}

export function Transcript({
  entries,
  lang,
  failure = null,
  onRetry,
  otpFoot,
  afterHandoff,
  detective = false,
  onOpenTrace,
}: TranscriptProps) {
  const dict = dictionaries[lang];
  const otpEntryId = otpFoot ? lastEntryWith(entries, isOtpSendReceipt) : null;
  const handoffEntryId = afterHandoff ? lastEntryWith(entries, isHandoff) : null;
  return (
    <>
      {entries.map((entry) => (
        <EntryView
          key={entry.id}
          entry={entry}
          lang={lang}
          dict={dict}
          failure={failure?.entryId === entry.id ? failure : null}
          onRetry={onRetry}
          otpFoot={entry.id === otpEntryId ? otpFoot : undefined}
          afterHandoff={entry.id === handoffEntryId ? afterHandoff : undefined}
          detective={detective}
          onOpenTrace={onOpenTrace}
        />
      ))}
    </>
  );
}

function EntryView({
  entry,
  lang,
  dict,
  failure,
  onRetry,
  otpFoot,
  afterHandoff,
  detective,
  onOpenTrace,
}: {
  entry: Entry;
  lang: Lang;
  dict: Dictionary;
  failure: PendingFailure | null;
  onRetry?: () => void;
  otpFoot?: ReactNode;
  afterHandoff?: ReactNode;
  detective: boolean;
  onOpenTrace?: (entryId: string) => void;
}) {
  switch (entry.kind) {
    case "customer": {
      const failed = entry.status === "failed";
      return (
        <>
          <div
            className="pb-msg pb-msg--customer"
            data-status={failed ? "failed" : undefined}
            lang={entry.lang === lang ? undefined : entry.lang}
          >
            <Sender name={dict.chat.roles.customer} />
            <MessageText text={entry.text} />
            <span className="pb-msg__time">{formatClock(entry.at, entry.lang)}</span>
          </div>
          {failed && <UnsentLine dict={dict} failure={failure} onRetry={onRetry} />}
        </>
      );
    }
    case "assistant":
      return (
        <>
          <Blocks blocks={entry.blocks} turnLang={entry.lang} lang={lang} at={entry.at} otpFoot={otpFoot} afterHandoff={afterHandoff} />
          {detective && entry.trace && <TraceOpen dict={dict} trace={entry.trace} onOpen={onOpenTrace && (() => onOpenTrace(entry.id))} />}
        </>
      );
    case "agent":
      return (
        <div className="pb-msg pb-msg--agent">
          <span className="pb-msg__meta">
            <Icon name="user" />
            {dict.chat.roles.agent}
          </span>
          <MessageText text={entry.text} />
          <span className="pb-msg__time">{formatClock(entry.at, lang)}</span>
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

/** Under a message the API did not accept: what happened and, when it can be resent, "Reintentar". */
function UnsentLine({ dict, failure, onRetry }: { dict: Dictionary; failure: PendingFailure | null; onRetry?: () => void }) {
  const reason = failure?.reason ?? null;
  return (
    <p className="pb-unsent" role={reason ? "alert" : undefined}>
      <span>
        <Icon name="warning" />
        {reason ? `${dict.chat.notSent} ${reason}` : dict.chat.notSent}
      </span>
      {failure?.retry && onRetry && (
        <button className="pb-action" type="button" onClick={onRetry}>
          {dict.chat.retry}
          <Icon name="retry" />
        </button>
      )}
    </p>
  );
}
