// How assistant text is split into money and the rest: a list of amounts is a ledger, other amounts are marked,
// and anything else stays exactly as written.

import { describe, expect, test } from "bun:test";
import { inlineParts, ledgerRow, parseMoneyText } from "../src/app/chat/money-text";

const amountsOf = (line: string) => inlineParts(line).filter((part) => part.kind === "amount").map((part) => part.text);

describe("amounts", () => {
  test("a number with a currency, in each way the model writes one", () => {
    expect(amountsOf("Pagaste 214.475,55 COP en Falabella")).toEqual(["214.475,55 COP"]);
    expect(amountsOf("Saldo: $108,448.51 USD y R$ 25,00")).toEqual(["$108,448.51 USD", "R$ 25,00"]);
    expect(amountsOf("Available: COP 1.234.567")).toEqual(["COP 1.234.567"]);
    expect(amountsOf("25000 COP.")).toEqual(["25000 COP"]);
  });

  test("a number without a currency is not money", () => {
    for (const line of ["Tu tarjeta •••• 4821", "a las 14:35", "Referencia aud_00000373", "en 2026", "código 123456"]) {
      expect(amountsOf(line)).toEqual([]);
    }
  });

  test("the text around an amount is kept, character for character", () => {
    const line = "Tu saldo disponible es 1.234.567,89 COP, sin movimientos pendientes.";
    expect(inlineParts(line).map((part) => part.text).join("")).toBe(line);
  });
});

describe("ledger rows", () => {
  test("a dated transaction", () => {
    expect(ledgerRow("- 2 oct.: Local Artisan Bakery — 25.000 COP")).toEqual({
      date: "2 oct.",
      label: "Local Artisan Bakery",
      amount: "25.000 COP",
      note: null,
    });
    expect(ledgerRow("• Oct 2: Uber Colombia - $108,448.51")).toEqual({ date: "Oct 2", label: "Uber Colombia", amount: "$108,448.51", note: null });
    expect(ledgerRow("1. 26 set.: Padaria — R$ 25,00")).toEqual({ date: "26 set.", label: "Padaria", amount: "R$ 25,00", note: null });
  });

  test("an account balance, without a date", () => {
    expect(ledgerRow("- Cuenta de ahorros: 1.234.567,89 COP")).toEqual({ date: null, label: "Cuenta de ahorros", amount: "1.234.567,89 COP", note: null });
  });

  test("a short note after the amount, in brackets or after a dash, is kept as the row's note", () => {
    expect(ledgerRow("- 21 sep: Uber Brasil — R$ 248,40 (liquidada)")).toEqual({
      date: "21 sep",
      label: "Uber Brasil",
      amount: "R$ 248,40",
      note: "liquidada",
    });
    expect(ledgerRow("- Oct 1: Falabella — 214.475,55 COP — pending")?.note).toBe("pending");
  });

  test("a line that is not a list item, has no amount or two, or goes on after it, is not a row", () => {
    expect(ledgerRow("2 oct.: Local Artisan Bakery — 25.000 COP")).toBeNull();
    expect(ledgerRow("- Bloquear la tarjeta")).toBeNull();
    expect(ledgerRow("- Falabella: 214.475,55 COP, que fue el 12 de septiembre")).toBeNull();
    expect(ledgerRow("- Falabella: 214.475,55 COP y una devolución de 5.000 COP")).toBeNull();
    expect(ledgerRow("- 25.000 COP")).toBeNull();
  });
});

describe("parseMoneyText", () => {
  test("text without a list of amounts is one text segment, line breaks kept", () => {
    const text = "Hola.\n\nTu saldo disponible es 1.234.567,89 COP.";
    const segments = parseMoneyText(text);
    expect(segments).toHaveLength(1);
    expect(segments[0]!.kind).toBe("text");
    if (segments[0]!.kind === "text") expect(segments[0]!.parts.map((part) => part.text).join("")).toBe(text);
  });

  test("an intro, a list of transactions and a closing line", () => {
    const text = [
      "Estas son tus últimas transacciones:",
      "",
      "- 2 oct.: Local Artisan Bakery — 25.000 COP",
      "- 1 oct.: Global Electronics Megastore — 350.000 COP",
      "- 26 sep.: D1 Tiendas — 392.983,91 COP",
      "",
      "¿Reconoces todas?",
    ].join("\n");
    const segments = parseMoneyText(text);
    expect(segments.map((segment) => segment.kind)).toEqual(["text", "ledger", "text"]);
    const [intro, ledger, closing] = segments;
    if (intro?.kind === "text") expect(intro.parts).toEqual([{ kind: "plain", text: "Estas son tus últimas transacciones:" }]);
    if (ledger?.kind === "ledger") {
      expect(ledger.rows.map((row) => row.amount)).toEqual(["25.000 COP", "350.000 COP", "392.983,91 COP"]);
      expect(ledger.rows[1]!.label).toBe("Global Electronics Megastore");
    }
    if (closing?.kind === "text") expect(closing.parts).toEqual([{ kind: "plain", text: "¿Reconoces todas?" }]);
  });

  test("a list line without an amount splits the ledger and stays text", () => {
    const text = "- 2 oct.: Bakery — 25.000 COP\n- y otras dos compras\n- 1 oct.: Falabella — 214.475,55 COP";
    expect(parseMoneyText(text).map((segment) => segment.kind)).toEqual(["ledger", "text", "ledger"]);
  });
});
