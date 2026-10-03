import { describe, expect, test } from "bun:test";
import type { HandoffDetail, Lang } from "@pattern-blue/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";
import type { Api } from "../src/api/client";
import { Composer, ComposerLocked, TranscriptLog } from "../src/app/Conversation";
import { AppServicesProvider, I18nProvider, type AppActor } from "../src/app/context";
import { useDecisions, type DecisionsProps } from "../src/app/Decisions";
import { HandoffCard } from "../src/app/HandoffCard";
import { CaseMeta } from "../src/app/HandoffScreen";
import { GlanceNumbers, HandoffTables, NotHelpfulList, ToolCallsTable, ToReviewList } from "../src/app/MetricsScreen";
import { MatrixLegend, ModeGroup, RefusalBanner, ThresholdRow, ToolMatrix } from "../src/app/PolicyControl";
import { QueueRow, QueueTable } from "../src/app/QueueRow";
import { Alert, CaseRef } from "../src/app/ui";
import { floorOf } from "../src/machines/policy-draft";
import { AGENT_EMAIL, closedDetail, handoffDetail, handoffItems, metrics, toolPolicy, transcript } from "./support/fixtures";

const NOW = Date.UTC(2026, 8, 29, 10, 0, 0);
const html = (element: ReactElement, lang: Lang = "es") => renderToStaticMarkup(<I18nProvider lang={lang}>{element}</I18nProvider>);
const count = (text: string, needle: string | RegExp) => (typeof needle === "string" ? text.split(needle).length - 1 : (text.match(needle) ?? []).length);
/** What a reader sees: the markup without its tags and attributes. */
const visible = (markup: string) => markup.replace(/<[^>]*>/g, " ").replace(/\s+/g, " ");

const items = handoffItems(NOW);
const [urgent, high, assigned, queued] = items as [(typeof items)[number], (typeof items)[number], (typeof items)[number], (typeof items)[number]];
const noop = () => {};
const rowProps = { now: NOW, me: AGENT_EMAIL, open: false, pinned: false, up: false, decided: false, onOpen: noop, onClose: noop, onDecided: noop };

describe("the case id", () => {
  test("is mono in groups of four, and its text is the plain id", () => {
    const markup = html(<CaseRef value="hnd_kfjwqzrtmvnpaxeb" />);
    expect(markup).toBe('<span class="pb-caseref"><span>hnd_</span><span>kfjw</span><span>qzrt</span><span>mvnp</span><span>axeb</span></span>');
    expect(markup.replace(/<[^>]*>/g, "")).toBe("hnd_kfjwqzrtmvnpaxeb");
    expect(html(<CaseRef value="hnd_kfjwqzrtmvnpaxeb" large />)).toContain('class="pb-caseref pb-caseref--lg"');
  });
});

describe("QueueRow", () => {
  test("leads with the priority, then the case in words, with the id in mono on the second line", () => {
    const markup = html(<QueueRow item={urgent} {...rowProps} />);
    expect(markup).toContain('class="pb-crow" role="row"');
    for (const col of ["pri", "case", "who", "wait", "peek"]) expect(markup).toContain(`data-col="${col}"`);
    expect(markup.indexOf('data-col="pri"')).toBeLessThan(markup.indexOf('data-col="case"'));
    expect(markup).toContain('<a class="pb-crow__title" href="#/handoffs/hnd_qwertyuiopasdfgh"');
    expect(markup).toContain(">Fraude sospechado</a>");
    expect(markup).toContain("Operaciones de fraude");
    expect(markup).toContain('<span class="pb-crow__amount">USD 139.99</span>');
    expect(markup).toContain('<span class="pb-caseref"><span>hnd_</span><span>qwer</span>');
  });

  test("speaks words, and keeps the raw enums for the tooltip only", () => {
    const markup = html(<QueueRow item={urgent} {...rowProps} />);
    expect(markup).toContain('data-tone="danger" title="URGENT"');
    expect(markup).toContain("Urgente");
    for (const raw of ["URGENT", "FRAUD_OPERATIONS", "SUSPECTED_FRAUD", "QUEUED"]) expect(visible(markup)).not.toContain(raw);
  });

  test("says who: the place in line, you, or the agent who holds it", () => {
    expect(html(<QueueRow item={urgent} {...rowProps} />)).toContain("En cola · 1.º");
    expect(html(<QueueRow item={queued} {...rowProps} />)).toContain("En cola · 3.º");
    const other = html(<QueueRow item={assigned} {...rowProps} />);
    expect(other).toContain('data-other=""');
    expect(other).toContain("marta@demo.local");
    const mine = html(<QueueRow item={{ ...assigned, assigned_agent: AGENT_EMAIL }} {...rowProps} />);
    expect(mine).toContain('data-me=""');
    expect(mine).toContain(">Tú</span>");
  });

  test("shows the wait in mm:ss and a closed chevron that opens the summary", () => {
    const markup = html(<QueueRow item={urgent} {...rowProps} />);
    expect(markup).toContain('class="pb-wait">07:42</span>');
    expect(markup).toContain('class="pb-peekbtn" aria-expanded="false" aria-controls="peek-hnd_qwertyuiopasdfgh" aria-label="Resumen del caso"');
    expect(markup).not.toContain("pb-peek ");
  });

  test("a row without a disputed charge has no amount; a decided one is dimmed", () => {
    expect(html(<QueueRow item={assigned} {...rowProps} />)).not.toContain("pb-crow__amount");
    expect(html(<QueueRow item={high} {...rowProps} decided />)).toContain('data-closed=""');
  });

  test("speaks the language it is given", () => {
    const markup = html(<QueueRow item={high} {...rowProps} />, "en");
    expect(markup).toContain("Dispute claim");
    expect(markup).toContain("Queued · #2");
    expect(markup).toContain(">High<");
  });

  test("the table has a labelled frame, four named columns and one row per case", () => {
    const markup = html(
      <QueueTable items={items} now={NOW} me={AGENT_EMAIL} openRef={null} pinned={false} decided={new Set()} onOpen={noop} onClose={noop} onDecided={noop} />,
    );
    expect(markup).toContain('class="pb-cases" role="table" aria-label="Cola de casos"');
    expect(count(markup, 'role="columnheader"')).toBe(5);
    for (const label of ["Prioridad", "Caso", "Quién", "Espera"]) expect(markup).toContain(`>${label}<`);
    expect(count(markup, 'class="pb-crow"')).toBe(items.length);
  });
});

describe("HandoffCard, the case summary", () => {
  const detail = handoffDetail({}, NOW);

  test("opens with what the customer asks, marked as the assistant's unverified summary", () => {
    const markup = html(<HandoffCard detail={detail} />);
    expect(markup.indexOf("Lo que pide el cliente")).toBeLessThan(markup.indexOf("Cargo disputado"));
    expect(markup).toContain('class="pb-said"');
    expect(markup).toContain("Resumen del asistente, sin verificar");
    expect(markup).not.toContain("model_unverified");
  });

  test("the disputed charge leads with the amount, then the merchant, the date, the card and a short id", () => {
    const markup = html(<HandoffCard detail={detail} />);
    expect(markup).toContain('<span class="pb-txn__amount">USD 139.99</span>');
    expect(markup).toContain("Global Electronics Megastore");
    expect(markup).toContain("2026-09-27 14:03 UTC");
    expect(markup).toContain("•••• 4821");
    expect(markup).toContain('title="txn_4f2a91"');
  });

  test("what the bank verified reads as sentences, with no raw enum on screen", () => {
    const markup = html(<HandoffCard detail={detail} />);
    expect(markup).toContain("Verificado por el banco");
    expect(markup).toContain("Identidad verificada con documento y código");
    expect(markup).toContain("La política exige revisión humana.");
    expect(markup).toContain("La política pide prioridad.");
    for (const raw of ["VERIFIED", "document_match_and_otp", "HANDOFF_REQUIRED", "PRIORITY"]) expect(visible(markup)).not.toContain(raw);
  });

  test("an unidentified or locked customer is said so", () => {
    const anonymous = handoffDetail({ summary: { ...detail.summary, verified_facts: { verification_state: "ANONYMOUS" }, verification_method: "none" } }, NOW);
    const locked = handoffDetail({ summary: { ...detail.summary, verified_facts: { verification_state: "LOCKED" } } }, NOW);
    expect(html(<HandoffCard detail={anonymous} />)).toContain("Cliente sin identificar");
    expect(html(<HandoffCard detail={locked} />)).toContain("Bloqueado tras fallar la verificación");
  });

  test("what the assistant did lists its writes with the audit id, then the customer's answer", () => {
    const markup = html(<HandoffCard detail={detail} />);
    expect(markup).toContain("Bloqueó la tarjeta");
    expect(markup).toContain("aud_00020481");
    expect(markup).toContain("El cliente no respondió si el asistente le ayudó");
    const rated = html(<HandoffCard detail={handoffDetail({ feedback: { helpful: false, recorded_at: "2026-09-29T09:56:00Z" } }, NOW)} />);
    expect(rated).toContain("El cliente dijo que el asistente no le ayudó · 09:56");
  });

  test("the full log starts closed, one line per call with the result in words and the codes in a tooltip", () => {
    const markup = html(<HandoffCard detail={detail} />);
    expect(markup).toContain('class="pb-more" aria-expanded="false"');
    expect(markup).toContain("Registro de llamadas (5)");
    expect(markup).toMatch(/<div id="case-hnd_qwertyuiopasdfgh-log" hidden="">/);
    expect(count(markup, "<tr")).toBe(5);
    expect(markup).toContain('<tr data-refused=""><td>account.get_summary</td><td title="refused · STATE_NOT_ALLOWED">Rechazada, estado no permitido</td>');
    expect(html(<HandoffCard detail={detail} initiallyOpenLog />)).toContain('aria-expanded="true"');
  });

  test("never proposes a resolution and says whose decision it is", () => {
    const markup = html(<HandoffCard detail={detail} />);
    expect(markup).toContain("El asistente no resuelve disputas. La decisión es tuya.");
    expect(markup).not.toMatch(/recomend.*aprob|sugerimos/i);
  });

  test("an English card", () => {
    const markup = html(<HandoffCard detail={detail} />, "en");
    expect(markup).toContain("What the customer asks");
    expect(markup).toContain("Identity verified with a document and a code");
    expect(markup).toContain("The assistant does not resolve disputes. The decision is yours.");
  });
});

describe("the case header line", () => {
  test("priority, department, who and the wait, then the id with Copiar", () => {
    const mine = html(<CaseMeta detail={handoffDetail({ status: "ASSIGNED", queue_position: null, assigned_agent: AGENT_EMAIL, assigned_at: "2026-09-29T09:55:00Z" }, NOW)} me={AGENT_EMAIL} now={NOW} />);
    expect(mine).toContain("Urgente");
    expect(mine).toContain("Operaciones de fraude");
    expect(mine).toContain('data-me="">Tuyo desde 09:55');
    expect(mine).toContain("esperó");
    expect(mine).toContain('class="pb-caseref pb-caseref--lg"');
    expect(mine).toContain('<button type="button" class="pb-linkbtn">Copiar</button>');
    const waiting = html(<CaseMeta detail={handoffDetail({}, NOW)} me={AGENT_EMAIL} now={NOW} />);
    expect(waiting).toContain("En cola, 1.º");
    expect(waiting).toContain("espera 07:42");
  });
});

const fakeApi = {} as Api;
const fakeActor = {} as AppActor;

function DecisionsProbe(props: DecisionsProps) {
  const view = useDecisions(props);
  return (
    <div>
      <div data-part="buttons">{view.buttons}</div>
      <div data-part="panel">{view.panel}</div>
    </div>
  );
}
const decisions = (detail: HandoffDetail, lang: Lang = "es") =>
  html(
    <AppServicesProvider actor={fakeActor} api={fakeApi}>
      <DecisionsProbe detail={detail} me={AGENT_EMAIL} conversationAlive messageLang={lang} />
    </AppServicesProvider>,
    lang,
  );

describe("the decisions", () => {
  test("Aprobar and Rechazar look the same, Escalar is quieter, and nothing is preselected", () => {
    const markup = decisions(handoffDetail({}, NOW));
    expect(markup).toContain('class="pb-btn pb-btn--sm pb-btn--secondary"><i class="pb-ico pb-ico--check" aria-hidden="true"></i>Aprobar</button>');
    expect(markup).toContain('class="pb-btn pb-btn--sm pb-btn--secondary"><i class="pb-ico pb-ico--x" aria-hidden="true"></i>Rechazar</button>');
    expect(markup).toContain('class="pb-btn pb-btn--sm pb-btn--ghost"><i class="pb-ico pb-ico--chev2" aria-hidden="true"></i>Escalar</button>');
    expect(markup).not.toContain("pb-btn--primary");
    expect(markup).not.toContain("pb-confirm");
  });

  test("only the outcomes banking-core lists are offered, and a blocked approval says why", () => {
    const rejectOnly = decisions(handoffDetail({ decisions: { ...handoffDetail().decisions, outcomes: ["REJECTED"] } }, NOW));
    expect(rejectOnly).not.toContain(">Aprobar<");
    expect(rejectOnly).toContain("Aprobar pide un cliente verificado.");
    const request = decisions(handoffDetail({ reason: "CUSTOMER_REQUEST", decisions: { outcomes: ["RESOLVED"], reject_reasons: [], escalate_to: ["DISPUTES"], closing_messages: {} } }, NOW));
    expect(request).toContain(">Cerrar</button>");
    expect(request).not.toContain(">Rechazar<");
    expect(request).not.toContain("Aprobar pide");
  });

  test("another agent's case offers nothing to decide, and says who has it", () => {
    const markup = decisions(handoffDetail({ status: "ASSIGNED", queue_position: null, assigned_agent: "marta@demo.local", assigned_at: new Date(NOW).toISOString() }, NOW));
    expect(markup).toContain("Lo tiene marta@demo.local.");
    expect(markup).not.toContain("pb-btn");
  });

  test("a closed case shows its outcome, who closed it and that the customer was told", () => {
    const markup = decisions(closedDetail("REJECTED", AGENT_EMAIL, NOW));
    expect(markup).toContain('class="pb-done" role="status"');
    expect(markup).toContain("Rechazado por ti");
    expect(markup).toContain("Otro motivo");
    expect(markup).toContain("El cliente recibió el mensaje de cierre.");
    expect(markup).not.toContain("pb-btn");
  });
});

describe("the transcript", () => {
  const data = transcript({ takeover: { active: true, since: new Date(NOW).toISOString(), agent_ref: AGENT_EMAIL }, withAgentMessage: true }, NOW);

  test("puts the customer on the left and the bank on the right, each name once per run", () => {
    const markup = html(<TranscriptLog messages={data.messages} me={AGENT_EMAIL} holder={AGENT_EMAIL} />);
    expect(markup).toContain('role="log"');
    expect(count(markup, '<div class="pb-convo__grp">')).toBe(2);
    expect(count(markup, '<div class="pb-convo__grp pb-convo__grp--bank">')).toBe(3);
    expect(count(markup, "pb-msg--customer")).toBe(2);
    expect(count(markup, "pb-msg--assistant")).toBe(2);
    expect(count(markup, "pb-msg--agent")).toBe(1);
    expect(markup).toContain('<span class="pb-convo__who" data-me="">Tú</span>');
    expect(count(markup, ">Cliente</span>")).toBe(2);
  });

  test("the time sits at the end of each bubble", () => {
    const markup = html(<TranscriptLog messages={data.messages} me={AGENT_EMAIL} holder={AGENT_EMAIL} />);
    expect(count(markup, 'class="pb-msg__time"')).toBe(5);
    expect(markup).not.toContain("pb-msg__meta");
  });

  test("a receipt is one line with its audit id; joining is a line in the agent's words", () => {
    const markup = html(<TranscriptLog messages={data.messages} me={AGENT_EMAIL} holder={AGENT_EMAIL} />);
    expect(markup).toContain('<div class="pb-sys" data-tone="locked">');
    expect(markup).toContain("Tarjeta •••• 4821 bloqueada");
    expect(markup).toContain('<span class="pb-sys__ref">· aud_00020481</span>');
    expect(markup).toContain("Tomaste la conversación");
    expect(markup).not.toContain("pb-cmsg");
  });

  test("another agent is named by the first part of the e-mail", () => {
    const markup = html(<TranscriptLog messages={data.messages} me={AGENT_EMAIL} holder="marta@demo.local" />);
    expect(markup).toContain(">marta</span>");
    expect(markup).toContain("marta tomó la conversación");
  });

  test("a block it does not know degrades to a line, and an empty transcript says so", () => {
    const odd = [{ role: "assistant" as const, content: "x", blocks: [{ type: "carousel", items: [] }], created_at: new Date(NOW).toISOString() }];
    expect(html(<TranscriptLog messages={odd} me={AGENT_EMAIL} holder={null} />)).toContain("Bloque no mostrado (carousel)");
    expect(html(<TranscriptLog messages={[]} me={AGENT_EMAIL} holder={null} />)).toContain("Todavía no hay mensajes.");
  });
});

describe("the composer", () => {
  const props = { sending: false, failed: false, outbox: null, error: null, onSend: noop, onRetry: noop, onDiscard: noop };

  test("before the case is taken, one line and the way to take it", () => {
    const markup = html(<ComposerLocked reason="take" onTake={noop} />);
    expect(markup).toContain("Para responder y ver la conversación en vivo, toma el caso.");
    expect(markup).toContain(">Tomar caso</button>");
    expect(html(<ComposerLocked reason="other" />)).toContain("Otra persona tiene la conversación.");
  });

  test("once taken it is a labelled text area of up to 2000 characters, with one short note", () => {
    const markup = html(<Composer {...props} />);
    expect(markup).toContain('<span class="pb-sr">Respuesta al cliente</span>');
    expect(markup).toContain("<textarea");
    expect(markup).toContain('maxLength="2000"');
    expect(markup).toContain("El cliente lee tu texto tal cual. El asistente no lo ve.");
  });

  test("a message that was not sent stays visible with a retry that resends the same one", () => {
    const markup = html(<Composer {...props} failed outbox={{ text: "Hola", client_message_id: "abcd1234" }} error="turnInProgress" />);
    expect(markup).toContain('data-status="failed"');
    expect(markup).toContain("Hola");
    expect(markup).toContain("Reintenta y se reenvía el mismo mensaje.");
  });
});

describe("the tools by state matrix", () => {
  const policy = toolPolicy();
  const matrix = (lang: Lang = "es") =>
    html(<ToolMatrix tools={Object.keys(policy.code_floor)} floorOf={(tool) => floorOf(policy, tool)} enabled={(tool) => (policy.tools[tool] ?? []) as never} onCell={noop} onMaster={noop} />, lang);

  test("names the states once, in words, with the raw enum as the tooltip", () => {
    const markup = matrix();
    expect(count(markup, "<th scope")).toBe(8);
    expect(markup).toContain('title="OTP_PENDING"');
    expect(markup).toContain("Código pendiente");
    expect(count(visible(markup), "Código pendiente")).toBe(1); // the cells carry it in their accessible names only
  });

  test("a state outside the floor is a dot, not a button; one inside is a switch", () => {
    const markup = matrix();
    const card = markup.slice(markup.indexOf('data-tool="card.block"'), markup.indexOf("</tr>", markup.indexOf('data-tool="card.block"')));
    expect(count(card, 'class="pb-mx__cell" role="switch"')).toBe(1);
    expect(card).toContain('aria-checked="true" aria-label="card.block en Verificado"');
    expect(count(card, 'class="pb-mx__off"')).toBe(5);
    expect(card).toContain('aria-label="Sin identificar, fuera del piso del código"');
  });

  test("a disabled tool has its cells off and its switch off", () => {
    const markup = matrix();
    const summary = markup.slice(markup.indexOf('data-tool="account.get_summary"'), markup.indexOf("</tr>", markup.indexOf('data-tool="account.get_summary"')));
    expect(summary).toContain('aria-checked="false" aria-label="account.get_summary en Verificado"');
    expect(summary).toContain("Resumen de la cuenta. Empieza apagada.");
  });

  test("each switch is named by its tool", () => {
    expect(matrix()).toContain('aria-labelledby="tool-card-block"');
  });

  test("the legend shows the three kinds of cell", () => {
    const markup = html(<MatrixLegend />);
    for (const word of ["Encendida", "Apagada", "Fuera del piso del código"]) expect(markup).toContain(word);
  });

  test("a refused widening is a caution banner with the hazard stripe, and names the floor", () => {
    const markup = html(<RefusalBanner refusal={{ source: "local", tool: "card.block", state: "IDENTIFIED", floor: ["VERIFIED"] }} onDismiss={noop} />);
    expect(markup).toContain("pb-hazard");
    expect(markup).toContain("card.block no puede habilitarse en IDENTIFIED.");
    expect(markup).toContain("solo en VERIFIED");
  });
});

describe("thresholds and mode", () => {
  test("an untouched row is just the field", () => {
    const markup = html(<ThresholdRow currency="EUR" value="500.00" savedMinor={50000} onChange={noop} />);
    expect(markup).toContain('class="pb-thr"');
    expect(markup).not.toContain("Sin guardar");
    expect(markup).not.toContain("antes");
    expect(markup).not.toContain("pb-gauge");
  });

  test("an edited row says so and shows the old value; the USD row compares the demo charge", () => {
    const markup = html(<ThresholdRow currency="USD" value="100" savedMinor={50000} onChange={noop} />);
    expect(markup).toContain("Sin guardar");
    expect(markup).toContain("antes USD 500.00");
    expect(markup).toContain("El cargo de demo, USD 139.99, queda por encima.");
    expect(markup).toContain('data-state="caution"');
    expect(markup).toContain('aria-valuetext="Cargo de demo USD 139.99, umbral USD 100.00, por encima"');
    expect(html(<ThresholdRow currency="USD" value="500.00" savedMinor={50000} onChange={noop} />)).toContain("queda por debajo.");
  });

  test("an invalid threshold is marked invalid, with the reason, and shows no demo comparison", () => {
    const markup = html(<ThresholdRow currency="USD" value="cien" savedMinor={10000} onChange={noop} />);
    expect(markup).toContain('aria-invalid="true"');
    expect(markup).toContain("mayor que cero");
    expect(markup).not.toContain("pb-gauge");
  });

  test("the modes are words; the raw value is their tooltip", () => {
    const markup = html(<ModeGroup mode="block" onChange={noop} />);
    expect(markup).toContain('aria-checked="true" data-mode="block" title="block">Exigir handoff</button>');
    expect(markup).toContain('data-mode="flag" title="flag">Recomendar handoff</button>');
    expect(visible(markup)).not.toContain("(block)");
    expect(markup).toContain("La tarjeta no se bloquea por esto.");
  });
});

describe("AlertBanner", () => {
  test("a stripe is only for caution and critical", () => {
    expect(html(<Alert tone="caution" stripe eyebrow="X">a</Alert>)).toContain("pb-hazard");
    expect(html(<Alert tone="critical" stripe eyebrow="X">a</Alert>)).toContain("pb-hazard");
    expect(html(<Alert tone="info" stripe eyebrow="X">a</Alert>)).not.toContain("pb-hazard");
    expect(html(<Alert tone="success" stripe eyebrow="X">a</Alert>)).not.toContain("pb-hazard");
  });

  test("critical is an alert, the rest are status", () => {
    expect(html(<Alert tone="critical" eyebrow="X">a</Alert>)).toContain('role="alert"');
    expect(html(<Alert tone="caution" eyebrow="X">a</Alert>)).toContain('role="status"');
  });
});

describe("metrics at a glance", () => {
  const data = metrics(24, NOW);

  test("whether the assistant helped leads, with its share, its split, the change and how it was asked", () => {
    const markup = html(<GlanceNumbers data={data} />);
    expect(markup.indexOf("¿Ayudó el asistente?")).toBeLessThan(markup.indexOf("Identidad verificada"));
    expect(markup).toContain("pb-kpi pb-kpi--lead");
    expect(markup).toContain("78%<small>dijo que sí</small>");
    expect(markup).toContain("7 sí · 2 no");
    expect(markup).toContain('data-dir="up"');
    expect(markup).toContain("+7 pts");
    expect(markup).toContain("frente a las 24 h anteriores");
    expect(markup).toContain("El chat lo pregunta tras un traspaso. Respondieron 9 de 12 clientes.");
  });

  test("verification, cards blocked and cases to a person, each against the window before", () => {
    const markup = html(<GlanceNumbers data={data} />);
    expect(markup).toContain(">84%<");
    expect(markup).toContain("31 de 37 códigos enviados");
    expect(markup).toContain("−5 pts");
    expect(markup).toContain('data-dir="down"');
    expect(markup).toContain(">26<");
    expect(markup).toContain("+8");
    expect(markup).toContain("En cola ahora: 3");
    expect(markup).toContain("igual");
  });

  test("a counted change is neutral: more blocks or more cases are neither good nor bad", () => {
    const markup = html(<GlanceNumbers data={data} />);
    expect(count(markup, 'data-neutral=""')).toBe(2);
  });

  test("with no answers the lead number says so instead of a share", () => {
    const quiet = { ...data, feedback: { helpful: 0, not_helpful: 0 } };
    expect(html(<GlanceNumbers data={quiet} />)).toContain("Nadie respondió en esta ventana.");
  });

  test("the cases that got a no link to the case", () => {
    const markup = html(<NotHelpfulList data={data} />);
    expect(count(markup, 'data-tone="no"')).toBe(2);
    expect(markup).toContain("Reclamo de disputa");
    expect(markup).toContain('href="#/handoffs/hnd_zxcvbnmasdfghjkl"');
    expect(html(<NotHelpfulList data={{ ...data, recent_not_helpful: [] }} />)).toContain("Nadie respondió que no en esta ventana.");
  });

  test("what needs a look shows only counts above zero", () => {
    const markup = html(<ToReviewList data={data} now={NOW} onOpenTools={noop} />);
    expect(markup).toContain("Una llamada terminó en error interno");
    expect(markup).toContain("card.block");
    expect(markup).toContain("La política frenó 12 llamadas");
    expect(markup).toContain("8 % de 158");
    expect(markup).toContain("3 casos esperan a una persona");
    const calm = { ...data, tool_calls: data.tool_calls.filter((row) => row.decision === "allowed"), queue: { waiting: 0, urgent: 0, oldest_created_at: null } };
    expect(html(<ToReviewList data={calm} now={NOW} onOpenTools={noop} />)).toContain("Nada pendiente.");
  });

  test("the tool table names each tool once and reads the result in words", () => {
    const markup = html(<ToolCallsTable rows={data.tool_calls} />);
    expect(count(markup, '<td data-col="name">card.block</td>')).toBe(1);
    expect(count(markup, "<tbody")).toBe(6); // one per tool
    expect(markup).toContain('title="refused · NOT_MATCHED"');
    expect(markup).toContain('<span class="pb-reason">sin coincidencia</span>');
    expect(visible(markup)).not.toContain("NOT_MATCHED");
  });

  test("the case tables list every value in words, outcomes included", () => {
    const markup = html(<HandoffTables handoffs={data.handoffs} />);
    for (const title of ["Por estado", "Por prioridad", "Por departamento", "Por resultado"]) expect(markup).toContain(title);
    expect(markup).toContain('<td title="PENDING">Pendiente</td><td data-col="count">0</td>');
    expect(markup).toContain('<td title="APPROVED">Aprobado</td>');
    expect(markup).toContain("25%"); // 3 of 12 queued
  });
});
