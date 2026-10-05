import { describe, expect, test } from "bun:test";
import { DRAFT_AGENT_LINE, suggestAgentLine, type AgentSuggestion, type HandoffDetail, type Lang } from "@pattern-blue/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";
import type { Api } from "../src/api/client";
import { Composer, composerKeyAction, ComposerLocked, TranscriptLog } from "../src/app/Conversation";
import { AppServicesProvider, I18nProvider, type AppActor } from "../src/app/context";
import { useDecisions, type DecisionsProps } from "../src/app/Decisions";
import { FLOWS, FlowCard, Identifiers, STATES, StateMachine, ToolsByState } from "../src/app/FlowsScreen";
import { HandoffCard } from "../src/app/HandoffCard";
import { CaseMeta } from "../src/app/HandoffScreen";
import { GlanceNumbers, HandoffTables, NotHelpfulList, ToolCallsTable, ToReviewList } from "../src/app/MetricsScreen";
import { MatrixLegend, ModeGroup, RefusalBanner, ThresholdRow, ToolMatrix } from "../src/app/PolicyControl";
import { QueueRow, QueueTable } from "../src/app/QueueRow";
import { Alert, CaseRef } from "../src/app/ui";
import { dictionaries } from "../src/i18n";
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
    expect(mine).toContain('<button type="button" class="pb-btn pb-btn--ghost pb-btn--sm">Copiar</button>');
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

  describe("the suggested reply", () => {
    const suggestion: AgentSuggestion = { scriptId: "chargeAboveThreshold", line: DRAFT_AGENT_LINE };
    const band = (markup: string) => markup.slice(markup.indexOf('<div class="pb-say"'), markup.indexOf("<form"));

    test("a band over the form carries the label of the script, the line, the demo tag and the hint", () => {
      const markup = html(<Composer {...props} suggestion={suggestion} />);
      expect(markup.indexOf('class="pb-say"')).toBeGreaterThan(-1);
      expect(markup.indexOf('class="pb-say"')).toBeLessThan(markup.indexOf("<form"));
      const text = visible(band(markup));
      expect(text).toContain("Respuesta sugerida");
      expect(text).toContain("Solo demo");
      expect(text).toContain("Cargo no reconocido, sobre el umbral");
      expect(text).toContain("Hola, soy del equipo de Disputas y ya tengo tu caso.");
      expect(text).toContain("No se envía sola y queda registrada con tu correo.");
      expect(text).toContain("Usar");
    });

    test("using it can only fill the composer: the option is a plain button outside the form, so it cannot submit", () => {
      const markup = html(<Composer {...props} suggestion={suggestion} />);
      expect(band(markup)).toContain('<button type="button" class="pb-cut pb-say__opt"');
      expect(markup.slice(markup.indexOf("<form"))).not.toContain("pb-say");
      // The draft starts empty, so nothing can be sent before "Usar" or typing.
      expect(markup.slice(markup.indexOf("<form"))).toContain('disabled=""');
    });

    test("it is named as a group by its title, and the line says its language", () => {
      const markup = html(<Composer {...props} suggestion={suggestion} />);
      const id = /aria-labelledby="([^"]+)"/.exec(band(markup))?.[1];
      expect(id).toBeDefined();
      expect(band(markup)).toContain(`id="${id}"`);
      expect(band(markup)).toContain('lang="es"');
    });

    test("with no suggestion there is no band", () => {
      expect(html(<Composer {...props} />)).not.toContain("pb-say");
      expect(html(<Composer {...props} suggestion={null} />)).not.toContain("pb-say");
    });

    test("while a message is sending, or after one failed to send, the option cannot be used", () => {
      expect(band(html(<Composer {...props} suggestion={suggestion} />))).not.toContain("disabled");
      expect(band(html(<Composer {...props} sending suggestion={suggestion} />))).toContain("disabled");
      const failed = html(<Composer {...props} failed outbox={{ text: "Hola", client_message_id: "abcd1234" }} error="unavailable" suggestion={suggestion} />);
      expect(band(failed)).toContain("disabled");
    });

    test("it speaks the language of the interface, and the line stays as written", () => {
      for (const [lang, title, label, hint] of [
        ["pt", "Resposta sugerida", "Cobrança não reconhecida, acima do limite", "Não é enviada sozinha"],
        ["en", "Suggested reply", "Unrecognized charge, above the threshold", "never sent on its own"],
      ] as const) {
        const text = visible(band(html(<Composer {...props} suggestion={suggestion} />, lang)));
        expect(text, lang).toContain(title);
        expect(text, lang).toContain(label);
        expect(text, lang).toContain(hint);
        expect(text, lang).toContain(DRAFT_AGENT_LINE);
      }
    });

    test("Enter sends once: a repeat of the held key (after \"Usar\" moved the focus here) is swallowed, and composing or Shift+Enter are left alone", () => {
      const key = { key: "Enter", shiftKey: false, isComposing: false, repeat: false };
      expect(composerKeyAction(key)).toBe("send");
      expect(composerKeyAction({ ...key, repeat: true })).toBe("swallow");
      expect(composerKeyAction({ ...key, shiftKey: true })).toBe("ignore");
      expect(composerKeyAction({ ...key, isComposing: true })).toBe("ignore");
      expect(composerKeyAction({ ...key, key: "a" })).toBe("ignore");
      expect(composerKeyAction({ ...key, key: "a", repeat: true })).toBe("ignore");
    });

    test("the screen derives it from the transcript the page already holds: the fixture's conversation opens no script", () => {
      expect(suggestAgentLine(transcript().messages)).toBeNull();
    });
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
    expect(markup).toContain("card.block no puede habilitarse en Identificado.");
    expect(markup).toContain("solo en Verificado");
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

describe("the flows screen", () => {
  test("the state machine walks the path to VERIFIED with the tool of each step, and names both exits", () => {
    const markup = html(<StateMachine />);
    for (const state of ["ANONYMOUS", "IDENTIFIED", "OTP_PENDING", "VERIFIED", "LOCKED", "HANDED_OFF"]) expect(markup).toContain(state);
    expect(markup.indexOf("customer.match")).toBeLessThan(markup.indexOf("otp.send"));
    expect(markup.indexOf("otp.send")).toBeLessThan(markup.indexOf("otp.verify"));
    expect(markup).toContain("pedir una persona siempre pasa");
  });

  test("the matrix draws the policy in force: a disabled tool reads as disabled, every cell says what it is", () => {
    const tools = toolPolicy();
    const markup = html(<ToolsByState tools={tools} />);
    expect(count(markup, "<tr")).toBe(Object.keys(tools.code_floor).length + 1);
    expect(markup).toContain('<b class="pb-t-mono">account.get_summary</b><span class="pb-t-small">desactivada</span>');
    expect(markup).toContain('aria-label="card.block: permitida en Verificado"');
    expect(markup).toContain('aria-label="card.block: no permitida en Sin identificar"');
    expect(markup).toContain('href="#/guardrails"');
  });

  test("the matrix is the Guardrails matrix, read only: the system's classes, a filled cell for allowed, no colour per state", () => {
    const tools = toolPolicy();
    const markup = html(<ToolsByState tools={tools} />);
    expect(markup).toContain('class="pb-mx bo-mx"');
    expect(count(markup, 'class="pb-mx__tool"')).toBe(Object.keys(tools.code_floor).length);
    const allowed = Object.values(tools.tools).reduce((total, states) => total + states.length, 0);
    expect(count(markup, 'class="pb-mx__cell"')).toBe(allowed);
    expect(count(markup, 'class="pb-mx__off"')).toBe(Object.keys(tools.code_floor).length * STATES.length - allowed);
    expect(count(markup, 'aria-checked="true"')).toBe(allowed);
    // every cell has its name, and it is not a button
    expect(count(markup, 'role="img"')).toBe(Object.keys(tools.code_floor).length * STATES.length);
    expect(markup).not.toContain("<button");
    // the headers are the system's chips with the state in words, the raw state in the tooltip
    expect(markup).toContain('<th scope="col"><span class="pb-chip" data-state="otp-pending" title="OTP_PENDING">');
    expect(markup).not.toContain("bo-flowstate");
    expect(markup).not.toContain("bo-scroll");
  });

  test("every flow has its steps in order, its outcomes and, for fraud, the example conversation", () => {
    for (const flow of FLOWS) {
      const markup = html(<FlowCard flow={flow} balanceEnabled={false} />);
      expect(count(markup, 'class="pb-flow__item"')).toBe(flow.steps.length);
      expect(count(markup, 'class="bo-outcome"')).toBe(flow.outcomes.length);
      expect(markup.includes('class="bo-example"')).toBe(flow.example !== undefined);
    }
    const fraud = html(<FlowCard flow={FLOWS.find((flow) => flow.id === "fraud")!} balanceEnabled={false} />, "pt");
    expect(fraud).toContain("SUSPECTED_FRAUD");
    expect(fraud).toContain("Exemplo");
    const balance = (enabled: boolean) => html(<FlowCard flow={FLOWS.find((flow) => flow.id === "balance")!} balanceEnabled={enabled} />, "en");
    expect(balance(false)).toContain("Today: account.get_summary disabled");
    expect(balance(true)).toContain("Today: account.get_summary enabled");
  });

  const cards = (lang: Lang = "es") => FLOWS.map((flow) => ({ flow, markup: html(<FlowCard flow={flow} balanceEnabled={false} />, lang) }));

  test("tool names are in the data type everywhere and nothing is left of the unstyled `bo-raw`", () => {
    const tools = toolPolicy();
    const markup = [html(<StateMachine />), html(<ToolsByState tools={tools} />), ...cards().map((card) => card.markup)].join("\n");
    expect(markup).not.toContain("bo-raw");
    for (const tool of ["customer.match", "otp.send", "otp.verify"]) expect(html(<StateMachine />)).toContain(`<span class="pb-t-mono">${tool}</span>`);
    for (const tool of Object.keys(tools.code_floor)) expect(html(<ToolsByState tools={tools} />)).toContain(`<b class="pb-t-mono">${tool}</b>`);
    for (const { flow, markup: card } of cards()) {
      for (const step of flow.steps) if (step.tool) expect(card).toContain(`<p class="pb-t-mono">${step.tool}</p>`);
    }
  });

  test("the edge between two states draws the arrow glyph, not the text character", () => {
    const markup = html(<StateMachine />);
    expect(count(markup, '<i class="pb-ico pb-ico--arrow" aria-hidden="true"></i>')).toBe(3);
    expect(markup).not.toContain("→");
    expect(count(markup, "pb-cut bo-node")).toBe(4);
  });

  test("the steps are the system's numbered list: no digits in the markup, a chip only where the state changes", () => {
    for (const { flow, markup } of cards()) {
      const list = /<ol class="pb-flow pb-flow--col" role="list">(.*?)<\/ol>/s.exec(markup)?.[1] ?? "";
      expect(list, flow.id).not.toBe("");
      expect(count(list, "<li")).toBe(flow.steps.length);
      expect(visible(list), flow.id).not.toMatch(/\d/);
      const items = list.split("<li ").slice(1);
      flow.steps.forEach((step, index) => {
        const changed = step.state !== undefined && step.state !== flow.steps[index - 1]?.state;
        expect(items[index]!.includes("pb-flow__state"), `${flow.id} step ${index}`).toBe(changed);
        if (changed) expect(items[index]).toContain(`data-state="${step.state!.toLowerCase().replace(/_/g, "-")}"`);
      });
    }
    // the unrecognized flow: identify, verify and find the charge change the state; block keeps VERIFIED
    expect(count(cards()[0]!.markup, "pb-flow__state")).toBe(3);
  });

  test("each outcome carries a chip with a word and a glyph; handing off to Fraude is not danger", () => {
    const kinds = FLOWS.flatMap((flow) => flow.outcomes.map((outcome) => `${outcome.text}=${outcome.kind}`));
    expect(kinds).toEqual([
      "flows.unrecognized.out.auto=auto",
      "flows.unrecognized.out.handoff=handoff",
      "flows.unrecognized.out.person=handoff",
      "flows.fraud.out.auto=auto",
      "flows.fraud.out.handoff=handoff",
      "flows.fraud.out.urgent=urgent",
      "flows.lost.out.auto=auto",
      "flows.lost.out.locked=handoff",
      "flows.lost.out.thirdParty=handoff",
      "flows.balance.out.enabled=auto",
      "flows.balance.out.disabled=info",
      "flows.balance.out.payments=auto",
    ]);
    for (const { flow, markup } of cards()) {
      const rows = markup.split('<li class="bo-outcome">').slice(1);
      expect(rows.length).toBe(flow.outcomes.length);
      for (const row of rows) expect(row).toMatch(/^<span class="pb-chip" data-(state|tone)="[a-z-]+"><i class="pb-ico pb-ico--[a-z0-9-]+" aria-hidden="true"><\/i>(Automático|Handoff|Urgente|Informativo)<\/span>/);
    }
    const fraud = cards()[1]!.markup;
    expect(count(fraud, 'data-tone="danger"')).toBe(1);
    expect(fraud).toContain('data-state="handed-off"');
  });

  test("the outcome words follow the language", () => {
    expect(visible(cards("en")[1]!.markup)).toContain("Urgent");
    expect(visible(cards("pt")[3]!.markup)).toContain("Informativo");
    expect(visible(cards("en")[0]!.markup)).toContain("Automatic");
  });

  test("the notes are a compact list under one label; only the pending one is an alert, in caution and never striped", () => {
    for (const { flow, markup } of cards()) {
      const normal = flow.notes.filter((note) => !note.pending).length;
      const pending = flow.notes.length - normal;
      expect(count(markup, 'class="pb-alert"'), flow.id).toBe(pending);
      expect(count(markup, 'data-tone="caution"'), flow.id).toBe(pending);
      expect(markup).not.toContain("pb-alert--stripe");
      expect(markup).not.toContain("pb-hazard");
      expect(count(markup, '<p class="pb-t-label">Notas</p>'), flow.id).toBe(normal > 0 ? 1 : 0);
      expect(count(markup, '<ul class="bo-notelist">'), flow.id).toBe(normal > 0 ? 1 : 0);
      expect(count(markup, '<li><i class="pb-ico pb-ico--info" aria-hidden="true"></i><span class="pb-t-small">'), flow.id).toBe(normal);
      expect(markup).not.toContain("pb-alert__eyebrow\">Nota<");
    }
    // one alert on the whole page: the vishing gap
    expect(cards().reduce((total, card) => total + count(card.markup, 'class="pb-alert"'), 0)).toBe(1);
    expect(cards()[1]!.markup).toContain('<span class="pb-alert__eyebrow">Sin cubrir</span>');
    expect(visible(cards("en")[1]!.markup)).toContain("Notes");
  });

  test("the example conversation reuses the chat's messages and keeps the trace line as plain mono", () => {
    const markup = cards()[1]!.markup;
    expect(count(markup, 'class="pb-msg pb-msg--customer"')).toBe(2);
    expect(count(markup, 'class="pb-msg pb-msg--assistant"')).toBe(3);
    expect(count(markup, 'class="bo-example__trace pb-t-mono"')).toBe(2);
    expect(markup).toContain('<span class="pb-msg__meta">Cliente</span>');
    expect(markup).toContain('<h3 class="pb-t-h3">Ejemplo</h3>');
    expect(markup).toContain('<h3 class="pb-t-h3">Salidas</h3>');
  });

  test("the matrix's row header beats the system's label style, so a tool shows as written, in mono", async () => {
    const css = await Bun.file(new URL("../src/app/app.css", import.meta.url)).text();
    const rule = /^\.bo-mx tbody th:first-child \{([^}]*)\}/m.exec(css)?.[1] ?? "";
    expect(rule).toContain("text-transform: none;");
    expect(rule).toContain("letter-spacing: normal;");
    expect(rule).toContain("font: inherit;");
    expect(css).toMatch(/^\.bo-mx \.pb-mx__tool b \{[^}]*font-family: var\(--font-mono\);/m);
    expect(css).toMatch(/^\.bo-mx \.pb-mx__tool \{ min-width: 0; \}/m);
    // the rule it has to beat: `.pb-mx th:first-child` (class, element, pseudo-class); ours has one more element
    const local = await Bun.file(new URL("../../../packages/design-tokens/local.css", import.meta.url)).text();
    expect(local).toMatch(/^\.pb-mx th:first-child, \.pb-mx th:last-child \{[^}]*text-transform: uppercase;/m);
    // the row header stays a th with scope=row
    expect(html(<ToolsByState tools={toolPolicy()} />)).toContain('<th scope="row"><span class="pb-mx__tool">');
  });

  test("every state chip of the screen carries the word, with the raw state in its tooltip", () => {
    const machine = html(<StateMachine />);
    const words = { ANONYMOUS: "Sin identificar", IDENTIFIED: "Identificado", OTP_PENDING: "Código pendiente", VERIFIED: "Verificado", LOCKED: "Bloqueado", HANDED_OFF: "Con agente" };
    for (const [state, word] of Object.entries(words)) expect(machine).toContain(`title="${state}"><i class="pb-ico`);
    expect([...machine.matchAll(/<span class="pb-chip" data-state="[a-z-]+" title="([A-Z_]+)">(?:<i[^>]*><\/i>)([^<]*)<\/span>/g)].map((match) => [match[1], match[2]])).toEqual([
      ["ANONYMOUS", words.ANONYMOUS],
      ["IDENTIFIED", words.IDENTIFIED],
      ["OTP_PENDING", words.OTP_PENDING],
      ["VERIFIED", words.VERIFIED],
      ["LOCKED", words.LOCKED],
      ["HANDED_OFF", words.HANDED_OFF],
    ]);
    // no chip shows an enum
    for (const markup of [machine, html(<ToolsByState tools={toolPolicy()} />), ...cards().map((card) => card.markup)]) {
      expect(markup).not.toMatch(/<\/i>(ANONYMOUS|IDENTIFIED|OTP_PENDING|VERIFIED|LOCKED|HANDED_OFF)<\/span>/);
    }
    // and the prose of the screen uses the same words: no raw state in the three languages
    for (const lang of ["es", "pt", "en"] as const) {
      // the machine's trace lines of the example are log output: they keep the raw state
      const screen = [html(<StateMachine />, lang), html(<ToolsByState tools={toolPolicy()} />, lang), ...cards(lang).map((card) => card.markup)].join(" ").replace(/<li class="bo-example__trace[^>]*>.*?<\/li>/g, "");
      expect(visible(screen), lang).not.toMatch(/\b(ANONYMOUS|IDENTIFIED|OTP_PENDING|VERIFIED|LOCKED|HANDED_OFF)\b/);
    }
  });

  test("a node's description says something the chip's word does not", () => {
    for (const lang of ["es", "pt", "en"] as const) {
      const states = dictionaries[lang].flows.fsm.states;
      const chips = dictionaries[lang].enums.state;
      for (const state of Object.keys(states) as (keyof typeof states)[]) expect(states[state].toLowerCase(), `${lang} ${state}`).not.toBe(chips[state].toLowerCase());
    }
  });

  test("the identifiers helper puts a tool, a code and a snake_case name in the data type and leaves the words alone", () => {
    const text = "handoff.create desde cualquier estado: SUSPECTED_FRAUD, CUSTOMER_REQUEST, confirm_gate y account.get_summary; banking-core decide, 24 h.";
    const markup = renderToStaticMarkup(<Identifiers text={text} />);
    expect([...markup.matchAll(/<code class="pb-t-mono">([^<]*)<\/code>/g)].map((match) => match[1])).toEqual(["handoff.create", "SUSPECTED_FRAUD", "CUSTOMER_REQUEST", "confirm_gate", "account.get_summary"]);
    expect(markup.replace(/<[^>]*>/g, "")).toBe(text);
    expect(renderToStaticMarkup(<Identifiers text="Una disputa sin identificar espera un intento." />)).toBe("Una disputa sin identificar espera un intento.");
    // the dictionaries are not touched: the helper only wraps when it draws
    expect(dictionaries.es.flows.fsm.toHandedOff).not.toContain("<code");
  });

  test("the prose of the screen shows the identifiers of the dictionaries in the data type", () => {
    expect(html(<StateMachine />)).toContain('<code class="pb-t-mono">handoff.create</code> desde cualquier estado');
    const fraud = html(<FlowCard flow={FLOWS.find((flow) => flow.id === "fraud")!} balanceEnabled={false} />);
    expect(fraud).toContain('<code class="pb-t-mono">SUSPECTED_FRAUD</code>');
    const lost = html(<FlowCard flow={FLOWS.find((flow) => flow.id === "lost")!} balanceEnabled={false} />);
    expect(lost).toContain('<code class="pb-t-mono">CUSTOMER_LOCKED</code>');
    // what the helper finds in every text of the screen is an identifier: nothing else gets the mono type
    const found = new Set<string>();
    for (const lang of ["es", "pt", "en"] as const) {
      const values = (node: unknown): string[] => (typeof node === "string" ? [node] : Object.values(node as object).flatMap(values));
      const leaves = values(dictionaries[lang].flows).join(" ");
      for (const match of renderToStaticMarkup(<Identifiers text={leaves} />).matchAll(/<code class="pb-t-mono">([^<]*)<\/code>/g)) found.add(match[1]!);
    }
    expect([...found].sort()).toEqual(["CUSTOMER_LOCKED", "CUSTOMER_REQUEST", "SUSPECTED_FRAUD", "SUSPICIOUS_ACTIVITY", "account.get_summary", "card.block", "confirm_gate", "customer.match", "handoff.create", "kb.search", "transaction.list_recent"].sort());
  });

  test("the path of states is a row from 1120px, where it fits, and a column below: the same node width, the edge as a small row under its node", async () => {
    const css = await Bun.file(new URL("../src/app/app.css", import.meta.url)).text();
    const block = /@media \(max-width: 1119px\) \{([^@]*?)\n\}/.exec(css)?.[1] ?? "";
    expect(block).toContain(".bo-path { flex-direction: column; flex-wrap: nowrap; align-items: stretch;");
    expect(block).toContain(".bo-path__item { flex-direction: column; align-items: stretch;");
    expect(block).toContain(".bo-edge { grid-auto-flow: column; justify-content: start;");
    expect(block).toContain(".bo-edge .pb-ico { order: -1; transform: rotate(90deg); }");
    // nothing in the narrow range keeps the row direction, and the desktop rules do not set a direction of their own
    expect(block).not.toContain("flex-direction: row");
    const desktop = css.replace(block, "");
    expect(desktop).toMatch(/^\.bo-path__item \{ display: flex; align-items: center; gap: var\(--space-2\); \}/m);
    expect(desktop).not.toMatch(/\.bo-path__item[^{]*\{[^}]*flex-direction/);
    // the markup keeps the list and the edge's name for assistive technology, and the last node has no edge
    const machine = html(<StateMachine />);
    expect(machine).toContain('<ol class="bo-path">');
    expect(count(machine, 'class="bo-edge"')).toBe(3);
    expect(count(machine, 'aria-label="luego ')).toBe(3);
  });

  test("Volver a la cola, Cambiar en Guardrails, Copiar and Actualizar are the system's controls, and no link stands alone in the system's `pb-link` look", async () => {
    const read = (path: string) => Bun.file(new URL(path, import.meta.url)).text();
    const handoff = await read("../src/app/HandoffScreen.tsx");
    expect(handoff).toContain('<a className="pb-btn pb-btn--ghost pb-btn--sm bo-back" href="#/">');
    expect(handoff).toContain('<i className="pb-ico pb-ico--arrow pb-ico--flip" aria-hidden="true" />');
    expect(handoff).toContain('className="pb-btn pb-btn--ghost pb-btn--sm" onClick={copy}');
    const metrics = await read("../src/app/MetricsScreen.tsx");
    expect(metrics).toContain('<button type="button" className="pb-btn pb-btn--ghost pb-btn--sm" disabled={loading} onClick={() => send({ type: "REFRESH" })}>\n              <Icon name="retry" />');
    expect(html(<ToolsByState tools={toolPolicy()} />)).toContain('<a href="#/guardrails" class="pb-action">Cambiar en Guardrails<i class="pb-ico pb-ico--arrow" aria-hidden="true"></i></a>');
    // no `pb-link` or `pb-linkbtn` left in the screens, and the stylesheet does not define a link-like button
    const dir = new URL("../src/app/", import.meta.url).pathname;
    for (const file of new Bun.Glob("*.tsx").scanSync(dir)) expect(await read(`../src/app/${file}`), file).not.toMatch(/pb-link\b|pb-linkbtn/);
    const local = await read("../../../packages/design-tokens/local.css");
    expect(local).not.toContain("pb-linkbtn");
    expect(local).toMatch(/^\.pb-ico--flip \{ transform: scaleX\(-1\); \}/m);
  });

  test("the flows block of app.css has no loose font size and no class the system already has", async () => {
    const css = await Bun.file(new URL("../src/app/app.css", import.meta.url)).text();
    const block = css.slice(css.indexOf("/* Flows:"));
    expect(block.length).toBeGreaterThan(500);
    expect(block).not.toMatch(/font(-size)?:[^;}]*\d(\.\d+)?(px|rem|em)\b/);
    expect(block).not.toMatch(/#[0-9a-fA-F]{3,8}\b/);
    const system = await Bun.file(new URL("../../../packages/design-tokens/src/components.css", import.meta.url)).text();
    const mine = new Set([...block.matchAll(/\.((?:bo|pb)-[a-z0-9_-]+)/g)].map((match) => match[1]!).filter((name) => name.startsWith("bo-")));
    for (const name of mine) expect(system.includes(`.${name}`), name).toBe(false);
    // the removed rules do not come back
    for (const gone of ["bo-raw", "bo-steps", "bo-step ", "bo-matrix", "bo-scroll", "bo-flow-notes", "::after { content"]) expect(block, gone).not.toContain(gone);
  });
});
