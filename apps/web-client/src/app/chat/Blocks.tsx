// The message blocks of one assistant turn, as the customer sees them.
//
//   text      a bubble; the only block the model writes
//   receipt   a structured message built from the receipt the engine re-read from the database
//   handoff   the customer view: department, priority, status, position and a fixed list. Never `summary`.
//
// `blocks` arrive raw and go through `parseBlocks` here: a type this build does not know, or a block that
// fails its schema, is left out and the rest of the turn is shown. The strings of receipts and handoffs are
// fixed per language and come from the dictionary; nothing the model says can make one appear.

import { parseBlocks, type HandoffBlock, type Lang, type RawBlock, type Receipt } from "@pattern-blue/contracts";
import { dictionaries, format, type Dictionary } from "../../i18n";
import { displayTarget, formatClock, maskCardNumbers } from "../../machines/chat-model";
import { Icon } from "../ui/Icon";
import { PriorityChip, ResourceChip, StateChip } from "../ui/StateChip";

export interface BlocksProps {
  blocks: readonly RawBlock[];
  /** The language the turn was written in: a text bubble in another language than the page is marked. */
  turnLang: Lang;
  /** The language of the page: engine-built blocks are shown in it. */
  lang: Lang;
  /** When the turn arrived, ISO. */
  at: string;
}

export function Blocks({ blocks, turnLang, lang, at }: BlocksProps) {
  const dict = dictionaries[lang];
  const { blocks: known } = parseBlocks(blocks);
  return (
    <>
      {known.map((block, index) => {
        switch (block.type) {
          case "text":
            return <TextBubble key={index} text={block.text} at={at} lang={lang} turnLang={turnLang} dict={dict} />;
          case "receipt":
            return <ReceiptMessage key={index} receipt={block.receipt} dict={dict} />;
          case "handoff":
            return <HandoffMessage key={index} block={block} dict={dict} />;
        }
      })}
    </>
  );
}

/** Message text: line breaks kept, and never a full card number, even if the model wrote one. */
export function MessageText({ text }: { text: string }) {
  return <span className="chat-text">{maskCardNumbers(text)}</span>;
}

function TextBubble({ text, at, lang, turnLang, dict }: { text: string; at: string; lang: Lang; turnLang: Lang; dict: Dictionary }) {
  return (
    <div className="pb-msg pb-msg--assistant" lang={turnLang === lang ? undefined : turnLang}>
      <span className="pb-msg__meta">
        {dict.chat.roles.assistant} · {formatClock(at, turnLang)}
      </span>
      <MessageText text={text} />
    </div>
  );
}

// --- Receipt ------------------------------------------------------------------------------------------------------

function receiptTitle(action: string, dict: Dictionary): string {
  const t = dict.chat.receipt;
  if (action === "card.block") return t.titleCardBlock;
  if (action === "otp.send") return t.titleOtpSend;
  if (action === "otp.verify") return t.titleOtpVerify;
  return t.titleOther;
}

/** What the target of this action is called; `null` when showing it would only show an internal reference. */
function targetLabel(action: string, dict: Dictionary): string | null {
  if (action === "card.block") return dict.chat.receipt.card;
  if (action === "otp.send") return dict.chat.receipt.destination;
  return null;
}

export function ReceiptMessage({ receipt, dict }: { receipt: Receipt; dict: Dictionary }) {
  const t = dict.chat.receipt;
  const label = targetLabel(receipt.action, dict);
  return (
    <article className="pb-cmsg" data-tone="receipt" aria-label={format(t.aria, { action: receipt.action })}>
      <div className="pb-cmsg__head">
        <span className="pb-cmsg__kicker">
          {t.kicker} · {receipt.action}
        </span>
      </div>
      <h3 className="pb-cmsg__title">{receiptTitle(receipt.action, dict)}</h3>
      <span className="pb-transition">
        <ResourceChip state={receipt.state_before} label={dict.chat.states[receipt.state_before]} />
        <Icon name="arrow" label={t.changedTo} />
        <ResourceChip state={receipt.state_after} label={dict.chat.states[receipt.state_after]} />
      </span>
      <dl className="pb-kv">
        {label && (
          <>
            <dt>{label}</dt>
            <dd>{displayTarget(receipt.target_masked)}</dd>
          </>
        )}
        <dt>{t.reference}</dt>
        <dd>{receipt.audit_id}</dd>
      </dl>
      <div className="pb-cmsg__foot">
        <Icon name="shield-check" />
        {t.foot}
      </div>
    </article>
  );
}

// --- Handoff, customer view ------------------------------------------------------------------------------------------

export function HandoffMessage({ block, dict }: { block: HandoffBlock; dict: Dictionary }) {
  const t = dict.chat.handoff;
  return (
    <article className="pb-cmsg" data-tone="handoff" aria-label={t.aria}>
      <div className="pb-cmsg__head">
        <span className="pb-cmsg__kicker">{t.kicker}</span>
        <StateChip state="handed-off" label={dict.chat.chip.handedOff} />
      </div>
      <h3 className="pb-cmsg__title">{format(t.title, { department: t.departments[block.department] })}</h3>
      <dl className="pb-kv">
        <dt>{t.reference}</dt>
        <dd>
          <span className="pb-caseid">{block.handoff_id}</span>
        </dd>
        <dt>{t.status}</dt>
        <dd className="pb-kv__text">{t.statuses[block.status]}</dd>
        {block.queue_position !== null && (
          <>
            <dt>{t.position}</dt>
            <dd className="pb-kv__text">{format(t.positionValue, { n: block.queue_position })}</dd>
          </>
        )}
        <dt>{t.priority}</dt>
        <dd className="pb-kv__text">
          <PriorityChip priority={block.priority} label={t.priorities[block.priority]} />
        </dd>
      </dl>
      <div>
        <span className="pb-cmsg__kicker chat-knows">{t.knowsTitle}</span>
        <ul className="pb-cmsg__list">
          {t.knows.map((line) => (
            <li key={line}>
              <Icon name="check" />
              <span>{line}</span>
            </li>
          ))}
        </ul>
      </div>
      <div className="pb-cmsg__foot">
        <Icon name="handoff" />
        {t.foot}
      </div>
    </article>
  );
}
