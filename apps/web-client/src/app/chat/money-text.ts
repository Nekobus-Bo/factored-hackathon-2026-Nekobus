// How an assistant bubble shows money: presentation only. The model writes recent transactions and balances as
// plain text, often a dash list (`- 2 oct.: Local Artisan Bakery — 25.000 COP`). This splits that text into
// a ledger (one row per list line that ends in an amount) and text whose amounts are marked, so the chat can
// line the amounts up and keep each one on one line. It never adds, computes or reorders a figure: every
// character shown is the model's, and a shape it does not recognise stays plain text. Pure functions, no React.

/** A piece of a text line: plain words, or an amount with its currency. */
export interface InlinePart {
  kind: "plain" | "amount";
  text: string;
}

/** A list line that ends in an amount: `date: label — amount`, the date optional. */
export interface LedgerRow {
  date: string | null;
  label: string;
  amount: string;
}

export type MoneySegment = { kind: "text"; parts: InlinePart[] } | { kind: "ledger"; rows: LedgerRow[] };

// A number with thousands groups (`214.475,55`, `108,448.51`, `1 234`) or without (`25000`, `25,00`).
const NUMBER = String.raw`(?:\d{1,3}(?:[.,  ]\d{3})+(?:[.,]\d{1,2})?|\d+(?:[.,]\d{1,2})?)`;
const CODE = "(?:COP|USD|BRL|EUR|MXN|PEN|CLP|ARS)";
const SYMBOL = String.raw`(?:R\$|US\$|\$|€)`;
const GAP = "[   ]?";
// An amount needs a currency, before or after the number: a year, a time, a card's last four or a receipt id
// is not money.
const AMOUNT_SOURCE =
  String.raw`(?<![\w.,$€])` +
  `(?:${SYMBOL}${GAP}${NUMBER}(?:${GAP}${CODE})?|${CODE}${GAP}${SYMBOL}?${GAP}${NUMBER}|${NUMBER}${GAP}${CODE})` +
  String.raw`(?![\w])`;

const amounts = () => new RegExp(AMOUNT_SOURCE, "g");

// `- `, `• `, `* `, `· ` or a number `1. ` / `1) ` at the start of a line.
const LIST_ITEM = /^\s*(?:[-•*·]|\d{1,2}[.)])\s+(.*)$/;
// What sits between the label and the amount: a dash, a colon, a comma.
const SEPARATOR_TAIL = /[\s—–\-:,]+$/;
// A short leading date before a colon: `2 oct.`, `Oct 2`, `2026-10-02`.
const LEADING_DATE = /^([^:]{1,12}?):\s+(.+)$/;

/** The amounts of a line, marked; the rest kept as is. */
export function inlineParts(line: string): InlinePart[] {
  const parts: InlinePart[] = [];
  let last = 0;
  for (const match of line.matchAll(amounts())) {
    if (match.index > last) parts.push({ kind: "plain", text: line.slice(last, match.index) });
    parts.push({ kind: "amount", text: match[0] });
    last = match.index + match[0].length;
  }
  if (last < line.length) parts.push({ kind: "plain", text: line.slice(last) });
  return parts;
}

/** A list line whose last thing is an amount, as a ledger row; anything else is not one. */
export function ledgerRow(line: string): LedgerRow | null {
  const item = LIST_ITEM.exec(line);
  if (!item) return null;
  const content = item[1]!.trimEnd();
  const found = [...content.matchAll(amounts())].at(-1);
  if (!found) return null;
  const rest = content.slice(found.index + found[0].length);
  if (!/^\s*\.?$/.test(rest)) return null;
  const left = content.slice(0, found.index).replace(SEPARATOR_TAIL, "");
  if (!left) return null;
  const dated = LEADING_DATE.exec(left);
  if (dated && /\d/.test(dated[1]!)) return { date: dated[1]!.trim(), label: dated[2]!.trim(), amount: found[0] };
  return { date: null, label: left.trim(), amount: found[0] };
}

/**
 * The text of an assistant bubble as segments. Without a ledger row it is one text segment, line breaks
 * kept, so a message with no list of amounts reads exactly as written. With one, consecutive rows form a
 * ledger and the text around it loses the blank lines at its edges (the ledger is a block of its own).
 */
export function parseMoneyText(text: string): MoneySegment[] {
  const lines = text.split("\n");
  const rows = lines.map(ledgerRow);
  if (rows.every((row) => row === null)) return [{ kind: "text", parts: inlineParts(text) }];

  const segments: MoneySegment[] = [];
  let pending: string[] = [];
  const flushText = () => {
    const chunk = pending.join("\n").replace(/^(?:[ \t]*\n)+|(?:\n[ \t]*)+$/g, "");
    if (chunk.trim()) segments.push({ kind: "text", parts: inlineParts(chunk) });
    pending = [];
  };
  lines.forEach((line, index) => {
    const row = rows[index];
    if (!row) {
      pending.push(line);
      return;
    }
    flushText();
    const previous = segments.at(-1);
    if (previous?.kind === "ledger") previous.rows.push(row);
    else segments.push({ kind: "ledger", rows: [row] });
  });
  flushText();
  return segments;
}
