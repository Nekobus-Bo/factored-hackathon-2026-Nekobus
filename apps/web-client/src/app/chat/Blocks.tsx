// The message blocks of one assistant turn, as the customer sees them.
//
//   text      a bubble; the only block the model writes
//   receipt   a structured message built from the receipt the engine re-read from the database: the result
//             and the receipt reference, with the state change and the database check one tap away. A
//             verified code is a system line with its reference.
//   handoff   the customer view: the department and the case reference. Never `summary`, and no queue
//             details (status, position, priority belong to the back office).
//
// `blocks` arrive raw and go through `parseBlocks` here: a type this build does not know, or a block that
// fails its schema, is left out and the rest of the turn is shown. The strings of receipts and handoffs are
// fixed per language and come from the dictionary; nothing the model says can make one appear.
//
// A text bubble shows money tidily (money-text.ts): a dash list of amounts as a ledger, every other amount kept
// on one line. Presentation only: the figures are the model's words, exactly as written.

import { parseBlocks, type HandoffBlock, type Lang, type RawBlock, type Receipt } from "@pattern-blue/contracts";
import { Fragment, useState, type ReactNode } from "react";
import { dictionaries, format, type Dictionary } from "../../i18n";
import { displayTarget, formatClock, formatClockSeconds, maskCardNumbers } from "../../machines/chat-model";
import { Icon, type IconName } from "../ui/Icon";
import { ResourceChip } from "../ui/StateChip";
import { parseMoneyText, type InlinePart } from "./money-text";

export interface BlocksProps {
  blocks: readonly RawBlock[];
  /** The language the turn was written in: a text bubble in another language than the page is marked. */
  turnLang: Lang;
  /** The language of the page: engine-built blocks are shown in it. */
  lang: Lang;
  /** When the turn arrived, ISO. */
  at: string;
  /** Shown inside this turn's `otp.send` receipt while its code is live: the countdown and the inbox action. */
  otpFoot?: ReactNode;
  /** Shown right after this turn's handoff block: the feedback line. */
  afterHandoff?: ReactNode;
}

export function Blocks({ blocks, turnLang, lang, at, otpFoot, afterHandoff }: BlocksProps) {
  const dict = dictionaries[lang];
  const { blocks: known } = parseBlocks(blocks);
  return (
    <>
      {known.map((block, index) => {
        switch (block.type) {
          case "text":
            return <TextBubble key={index} text={block.text} at={at} lang={lang} turnLang={turnLang} dict={dict} />;
          case "receipt":
            return (
              <ReceiptMessage
                key={index}
                receipt={block.receipt}
                dict={dict}
                lang={lang}
                foot={block.receipt.action === "otp.send" ? otpFoot : undefined}
              />
            );
          case "handoff":
            return (
              <Fragment key={index}>
                <HandoffMessage block={block} dict={dict} />
                {afterHandoff}
              </Fragment>
            );
        }
      })}
    </>
  );
}

/** Message text: line breaks kept, and never a full card number, even if the model wrote one. */
export function MessageText({ text }: { text: string }) {
  return <span className="chat-text">{maskCardNumbers(text)}</span>;
}

/**
 * Assistant text: what MessageText does, plus money set apart. A list of amounts is a ledger (date, label,
 * amount in a column); any other amount stays on one line. Customer and agent text never goes through this.
 */
export function AssistantText({ text }: { text: string }) {
  return (
    <>
      {parseMoneyText(maskCardNumbers(text)).map((segment, index) =>
        segment.kind === "text" ? (
          <span key={index} className="chat-text">
            <InlineMoney parts={segment.parts} />
          </span>
        ) : (
          <ul key={index} className="pb-ledger">
            {segment.rows.map((row, rowIndex) => (
              <li key={rowIndex} className="pb-ledger__row">
                {row.date !== null && <span className="pb-ledger__date">{row.date}</span>}
                <span className="pb-ledger__label" title={row.label}>
                  {row.label}
                </span>
                <span className="pb-ledger__amount">{row.amount}</span>
              </li>
            ))}
          </ul>
        ),
      )}
    </>
  );
}

function InlineMoney({ parts }: { parts: InlinePart[] }) {
  return (
    <>
      {parts.map((part, index) =>
        part.kind === "amount" ? (
          <span key={index} className="pb-amount">
            {part.text}
          </span>
        ) : (
          <Fragment key={index}>{part.text}</Fragment>
        ),
      )}
    </>
  );
}

/** The sender, for screen readers only: on screen the side and the face of the bubble say it. */
export function Sender({ name }: { name: string }) {
  return <span className="pb-sr">{name}: </span>;
}

function TextBubble({ text, at, lang, turnLang, dict }: { text: string; at: string; lang: Lang; turnLang: Lang; dict: Dictionary }) {
  return (
    <div className="pb-msg pb-msg--assistant" lang={turnLang === lang ? undefined : turnLang}>
      <Sender name={dict.chat.roles.assistant} />
      <AssistantText text={text} />
      <span className="pb-msg__time">{formatClock(at, turnLang)}</span>
    </div>
  );
}

// --- Receipt ------------------------------------------------------------------------------------------------------

const PROOF_LOOK: Record<string, { icon: IconName; tone?: "blocked" | "violet" }> = {
  "card.block": { icon: "card-blocked", tone: "blocked" },
  "otp.send": { icon: "mail", tone: "violet" },
};

/** A card.block on a card that was already blocked changed nothing: it says so, never "I blocked". */
function receiptTitle(receipt: Receipt, dict: Dictionary): string {
  const t = dict.chat.receipt;
  if (receipt.action === "card.block") {
    return receipt.state_before === "BLOCKED" ? t.titleCardAlreadyBlocked : t.titleCardBlock;
  }
  if (receipt.action === "otp.send") return t.titleOtpSend;
  return t.titleOther;
}

/** A title with its `{target}` set in the data face: `Bloqueé tu tarjeta •••• 4821`. */
function withTarget(template: string, target: string): ReactNode {
  const [before, after] = template.split("{target}");
  if (after === undefined) return template;
  return (
    <>
      {before}
      <span className="pb-proof__data">{target}</span>
      {after}
    </>
  );
}

export function ReceiptMessage({ receipt, dict, lang, foot }: { receipt: Receipt; dict: Dictionary; lang: Lang; foot?: ReactNode }) {
  if (receipt.action === "otp.verify" && (receipt.state_after === "VERIFIED" || receipt.state_after === "LOCKED")) {
    return <VerificationLine receipt={receipt} dict={dict} />;
  }
  return <ProofCard receipt={receipt} dict={dict} lang={lang} foot={foot} />;
}

/** A code check: a system line, verified or locked, that keeps its receipt reference. */
function VerificationLine({ receipt, dict }: { receipt: Receipt; dict: Dictionary }) {
  const verified = receipt.state_after === "VERIFIED";
  return (
    <p className="pb-sys" data-tone={verified ? "verified" : "locked"}>
      <span className="pb-sys__text">
        <Icon name={verified ? "shield-check" : "lock"} />
        {verified ? dict.chat.receipt.titleOtpVerify : dict.chat.chip.locked}
        <span className="pb-sys__ref">
          · {dict.chat.receipt.reference} {receipt.audit_id}
        </span>
      </span>
    </p>
  );
}

function ProofCard({ receipt, dict, lang, foot }: { receipt: Receipt; dict: Dictionary; lang: Lang; foot?: ReactNode }) {
  const t = dict.chat.receipt;
  const [open, setOpen] = useState(false);
  const look = PROOF_LOOK[receipt.action] ?? { icon: "shield-check" };
  const id = `receipt-${receipt.audit_id}`;
  return (
    <article className="pb-cut pb-proof" aria-labelledby={`${id}-title`}>
      <span className="pb-proof__icon" data-tone={look.tone} aria-hidden="true">
        <Icon name={look.icon} />
      </span>
      <p className="pb-proof__title" id={`${id}-title`}>
        {withTarget(receiptTitle(receipt, dict), displayTarget(receipt.target_masked))}
      </p>
      <button className="pb-proof__ref" type="button" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}>
        <Icon name="shield-check" />
        <span>
          {t.reference} <span className="pb-proof__data">{receipt.audit_id}</span>
        </span>
        <Icon name="chev1" />
      </button>
      <div className="pb-proof__more" id={id} hidden={!open}>
        {receipt.state_before === receipt.state_after ? (
          <span className="pb-transition">
            <ResourceChip state={receipt.state_after} label={dict.chat.states[receipt.state_after]} />
            <span>{t.unchanged}</span>
          </span>
        ) : (
          <span className="pb-transition">
            <ResourceChip state={receipt.state_before} label={dict.chat.states[receipt.state_before]} />
            <Icon name="arrow" label={t.changedTo} />
            <ResourceChip state={receipt.state_after} label={dict.chat.states[receipt.state_after]} />
          </span>
        )}
        <span>{format(t.verified, { time: formatClockSeconds(receipt.verified_at, lang) })}</span>
      </div>
      {foot}
    </article>
  );
}

// --- Handoff, customer view ------------------------------------------------------------------------------------------

export function HandoffMessage({ block, dict }: { block: HandoffBlock; dict: Dictionary }) {
  const t = dict.chat.handoff;
  const titleId = `handoff-${block.handoff_id}`;
  return (
    <article className="pb-cut pb-proof" data-tone="handoff" aria-labelledby={titleId}>
      <span className="pb-proof__icon" data-tone="violet" aria-hidden="true">
        <Icon name="handoff" />
      </span>
      <p className="pb-proof__title" id={titleId}>
        {format(t.title, { department: t.departments[block.department] })}
      </p>
      <p className="pb-proof__sub">
        {t.caseLabel} <span className="pb-proof__data">{block.handoff_id}</span>
      </p>
      <p className="pb-proof__note">{t.note}</p>
    </article>
  );
}
