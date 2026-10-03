import { describe, expect, test } from "bun:test";
import type { Lang } from "@pattern-blue/contracts";
import { renderToStaticMarkup } from "react-dom/server";
import type { ReactElement } from "react";
import { Composer, TranscriptLog } from "../src/app/Conversation";
import { I18nProvider } from "../src/app/context";
import { HandoffCard } from "../src/app/HandoffCard";
import { HandoffTables, ToolCallsTable } from "../src/app/MetricsScreen";
import { ModeGroup, RefusalBanner, ThresholdRow, ToolRow } from "../src/app/PolicyControl";
import { QueueRow, QueueTable } from "../src/app/QueueRow";
import { Alert } from "../src/app/ui";
import { floorOf } from "../src/machines/policy-draft";
import { AGENT_EMAIL, handoffDetail, handoffItems, metrics, toolPolicy, transcript } from "./support/fixtures";

const NOW = Date.UTC(2026, 8, 29, 10, 0, 0);
const html = (element: ReactElement, lang: Lang = "es") => renderToStaticMarkup(<I18nProvider lang={lang}>{element}</I18nProvider>);
const count = (text: string, needle: string | RegExp) => (typeof needle === "string" ? text.split(needle).length - 1 : (text.match(needle) ?? []).length);

const items = handoffItems(NOW);
const [urgent, high, assigned] = items as [(typeof items)[number], (typeof items)[number], (typeof items)[number]];

describe("QueueRow", () => {
  test("is the design system's row: role, cells, the case id as a stencil link", () => {
    const markup = html(<QueueRow item={urgent} now={NOW} />);
    expect(markup).toContain('class="pb-qrow" role="row"');
    for (const col of ["id", "pri", "dept", "status", "wait", "agent"]) expect(markup).toContain(`data-col="${col}"`);
    expect(markup).toContain('<a class="pb-caseid" href="#/handoffs/hnd_qwertyuiopasdfgh"');
    expect(markup).toContain(">hnd_qwertyuiopasdfgh</a>");
  });

  test("shows priority and department in words and as the raw enum", () => {
    const markup = html(<QueueRow item={urgent} now={NOW} />);
    expect(markup).toContain('<span class="pb-chip" data-tone="danger">');
    expect(markup).toContain("URGENT</span>");
    expect(markup).toContain("Urgente");
    expect(markup).toContain("Operaciones de fraude");
    expect(markup).toContain("FRAUD_OPERATIONS");
  });

  test("shows the status with the queue position, and the wait as mm:ss", () => {
    const markup = html(<QueueRow item={urgent} now={NOW} />);
    expect(markup).toContain("QUEUED");
    expect(markup).toContain("En cola · Posición 1");
    expect(markup).toContain("07:42");
    expect(markup).toContain("Sin asignar");
  });

  test("an assigned case shows its agent and no position", () => {
    const markup = html(<QueueRow item={assigned} now={NOW} />);
    expect(markup).toContain("ASSIGNED");
    expect(markup).toContain("marta@demo.local");
    expect(markup).not.toContain("Posición");
    expect(markup).toContain('data-tone="success"');
    expect(markup).toContain('data-tone="neutral"'); // NORMAL
  });

  test("HIGH is a warning chip", () => {
    expect(html(<QueueRow item={high} now={NOW} />)).toContain('data-tone="warning"');
  });

  test("speaks the language it is given", () => {
    const markup = html(<QueueRow item={urgent} now={NOW} />, "en");
    expect(markup).toContain("Fraud operations");
    expect(markup).toContain("Queued · Position 1");
    expect(markup).toContain("Unassigned");
    expect(html(<QueueRow item={urgent} now={NOW} />, "pt")).toContain("Operações de fraude");
  });

  test("the table has a labelled frame, six column headers and one row per case", () => {
    const markup = html(<QueueTable items={items} now={NOW} />);
    expect(markup).toContain('class="pb-queue bo-queue" role="table" aria-label="Cola de handoff"');
    expect(count(markup, 'role="columnheader"')).toBe(6);
    expect(count(markup, 'class="pb-qrow"')).toBe(4);
  });
});

describe("HandoffCard", () => {
  const detail = handoffDetail({}, NOW);

  test("carries the stored summary: verified facts, actions taken, the method and the open questions", () => {
    const markup = html(<HandoffCard detail={detail} now={NOW} me={AGENT_EMAIL} />);
    expect(markup).toContain('class="pb-card pb-handoff"');
    expect(markup).toContain("Hechos verificados");
    expect(markup).toContain("Acciones tomadas");
    expect(markup).toContain("Preguntas abiertas");
    // The verification method: in words and as stored.
    expect(markup).toContain("Documento y código OTP");
    expect(markup).toContain("(document_match_and_otp)");
    // Facts, from the stored record.
    expect(markup).toContain("VERIFIED</span>");
    expect(markup).toContain("Global Electronics Megastore");
    expect(markup).toContain("USD 139.99");
    expect(markup).toContain("•••• •••• •••• 4821");
    expect(markup).toContain("HANDOFF_REQUIRED");
    // Actions, with the refusal as a refusal.
    expect(markup).toContain("card.block");
    expect(markup).toContain("aud_00020481");
    expect(markup).toContain("Rechazada (refused) · Estado no permitido (STATE_NOT_ALLOWED) · aud_00020482");
    // The open question, marked as the model's unverified proposal.
    expect(markup).toContain("The customer says they do not recognize");
    expect(markup).toContain("Fuente: model_unverified (propuesta por el modelo, sin verificar)");
    expect(markup).toContain('<ol class="pb-questions">');
  });

  test("shows priority, department, reason and status as words beside the raw enums", () => {
    const markup = html(<HandoffCard detail={detail} now={NOW} />);
    expect(markup).toContain('<span class="pb-tag">FRAUD_OPERATIONS</span>');
    expect(markup).toContain('<span class="pb-tag">SUSPECTED_FRAUD</span>');
    expect(markup).toContain("Operaciones de fraude · Fraude sospechado · en espera 07:42 · posición 1 en la cola");
    expect(markup).toContain("URGENT</span>");
    expect(markup).toContain("QUEUED</span>");
  });

  test("the hazard stripe is for URGENT only", () => {
    expect(html(<HandoffCard detail={detail} now={NOW} />)).toContain('<span class="pb-hazard" aria-hidden="true"></span>');
    expect(html(<HandoffCard detail={handoffDetail({ priority: "HIGH" }, NOW)} now={NOW} />)).not.toContain("pb-hazard");
    expect(html(<HandoffCard detail={handoffDetail({ priority: "NORMAL" }, NOW)} now={NOW} />)).not.toContain("pb-hazard");
  });

  test("never proposes a resolution and says the assistant does not resolve disputes", () => {
    const markup = html(<HandoffCard detail={detail} now={NOW} />);
    expect(markup).toContain("El asistente no resuelve disputas.");
    expect(markup).not.toMatch(/reembols|refund|resolver el caso/i);
  });

  test("puts the actions it is given in the design system's action row, and none when it is given none", () => {
    const withAction = html(<HandoffCard detail={detail} now={NOW} actions={<button className="pb-btn pb-btn--primary pb-btn--sm">Tomar caso</button>} />);
    expect(withAction).toContain('<div class="pb-handoff__actions"><button class="pb-btn pb-btn--primary pb-btn--sm">Tomar caso</button></div>');
    expect(html(<HandoffCard detail={detail} now={NOW} />)).not.toContain("pb-handoff__actions");
  });

  test("says who holds an assigned case, and 'you' when it is you", () => {
    const mine = handoffDetail({ status: "ASSIGNED", queue_position: null, assigned_agent: AGENT_EMAIL }, NOW);
    expect(html(<HandoffCard detail={mine} now={NOW} me={AGENT_EMAIL} />)).toContain("Asignado a ti");
    expect(html(<HandoffCard detail={mine} now={NOW} me="other@demo.local" />)).toContain(`Asignado a ${AGENT_EMAIL}`);
  });

  test("keeps facts it has no label for, by their own key", () => {
    const odd = handoffDetail({}, NOW);
    odd.summary.verified_facts = { branch_code: "BOG-014", nested: { a: 1 }, none: null };
    const markup = html(<HandoffCard detail={odd} now={NOW} />);
    expect(markup).toContain("<dt>branch_code</dt>");
    expect(markup).toContain("BOG-014");
    expect(markup).toContain('{&quot;a&quot;:1}');
  });

  test("empty sections say so instead of disappearing", () => {
    const empty = handoffDetail({}, NOW);
    empty.summary = { verified_facts: {}, actions_taken: [], verification_method: "none", open_questions: [] };
    const markup = html(<HandoffCard detail={empty} now={NOW} />);
    expect(markup).toContain("No hay hechos verificados.");
    expect(markup).toContain("Todavía no hay acciones registradas.");
    expect(markup).toContain("No hay preguntas abiertas.");
  });

  test("an English card", () => {
    const markup = html(<HandoffCard detail={detail} now={NOW} />, "en");
    expect(markup).toContain("Verified facts");
    expect(markup).toContain("Actions taken");
    expect(markup).toContain("Open questions");
    expect(markup).toContain("The assistant does not resolve disputes.");
  });
});

describe("the tool by state matrix", () => {
  const policy = toolPolicy();
  const row = (tool: string, enabled = policy.tools[tool] ?? []) =>
    html(<ToolRow tool={tool} floor={floorOf(policy, tool)} enabled={enabled as never} onCell={() => {}} onMaster={() => {}} />);
  const cells = (markup: string) => [...markup.matchAll(/<button[^>]*role="switch"[^>]*>/g)].map((match) => match[0]);

  test("a cell outside the code floor is aria-disabled with an x, and the ones inside are not", () => {
    const markup = row("card.block");
    const all = cells(markup);
    expect(all).toHaveLength(6);
    const disabled = all.filter((cell) => cell.includes('aria-disabled="true"'));
    expect(disabled).toHaveLength(5);
    const toggleable = all.filter((cell) => !cell.includes("aria-disabled"));
    expect(toggleable).toHaveLength(1);
    expect(toggleable[0]).toContain('data-fsm="VERIFIED"');
    expect(toggleable[0]).toContain('aria-checked="true"');
    // Outside the floor: the reason is in the accessible name, and the glyph is the x.
    for (const state of ["ANONYMOUS", "IDENTIFIED", "OTP_PENDING", "LOCKED", "HANDED_OFF"]) {
      expect(markup).toContain(`aria-label="${state}: fuera del piso del código"`);
    }
    expect(count(markup, "pb-ico--x")).toBe(5);
  });

  test("the floor is shown, and where the tool is active", () => {
    const markup = row("otp.send");
    expect(markup).toContain('data-floor="IDENTIFIED, OTP_PENDING"');
    expect(markup).toContain("Piso del código: <b>IDENTIFIED, OTP_PENDING</b>");
    expect(markup).toContain("Activa en:");
    expect(markup).toContain("<b>IDENTIFIED, OTP_PENDING</b>");
  });

  test.each(Object.entries(toolPolicy().code_floor))("%s: exactly the states outside its floor are aria-disabled", (tool, floor) => {
    const markup = row(tool);
    const disabled = cells(markup).filter((cell) => cell.includes('aria-disabled="true"'));
    expect(disabled).toHaveLength(6 - floor.length);
    for (const cell of disabled) {
      const state = /data-fsm="(\w+)"/.exec(cell)?.[1] as never;
      expect(floor).not.toContain(state);
    }
  });

  test("a tool available in every state has nothing outside its floor", () => {
    const markup = row("handoff.create");
    expect(cells(markup).some((cell) => cell.includes("aria-disabled"))).toBe(false);
    expect(markup).toContain("Piso del código: <b>todos los estados</b>");
    expect(markup).toContain("<b>todos</b>");
  });

  test("a disabled tool says so in words, not only in the switch", () => {
    const off = row("account.get_summary");
    expect(off).toContain("<span>Apagada</span>");
    expect(off).toContain("<b>ninguno</b>");
    expect(off).toContain('data-state="unchecked"');
    expect(off).not.toContain('data-state="checked"');
    const on = row("card.block");
    expect(on).toContain("<span>Activa</span>");
    expect(on).toContain('data-state="checked"');
  });

  test("the switch is the design system's, on Ark UI's parts, and has a name", () => {
    const markup = row("card.block");
    expect(markup).toContain('class="pb-switch"');
    expect(markup).toContain('class="pb-switch__thumb"');
    expect(markup).toContain('type="checkbox"');
    expect(markup).toContain('aria-labelledby="tool-card-block"');
    expect(markup).toContain('id="tool-card-block"');
  });

  test("the legend and the note of a tool are there", () => {
    expect(row("card.block")).toContain("Bloqueo de tarjeta con comprobante.");
    expect(html(<ToolRow tool="card.block" floor={["VERIFIED"]} enabled={["VERIFIED"]} onCell={() => {}} onMaster={() => {}} />, "en")).toContain("Card block with a receipt.");
  });

  test("a refused widening is a caution banner with the hazard stripe, and names the floor", () => {
    const markup = html(<RefusalBanner refusal={{ source: "local", tool: "card.block", state: "ANONYMOUS", floor: ["VERIFIED"] }} onDismiss={() => {}} />);
    expect(markup).toContain('class="pb-alert pb-alert--stripe"');
    expect(markup).toContain('data-tone="caution"');
    expect(markup).toContain('class="pb-hazard"');
    expect(markup).toContain("card.block no puede habilitarse en ANONYMOUS.");
    expect(markup).toContain("El código lo permite solo en VERIFIED.");
    expect(markup).toContain("422");
  });

  test("the API's own 422 is shown the same way", () => {
    const markup = html(<RefusalBanner refusal={{ source: "api", messages: ["otp.send cannot be enabled in VERIFIED"] }} onDismiss={() => {}} />);
    expect(markup).toContain("pb-alert--stripe");
    expect(markup).toContain("otp.send cannot be enabled in VERIFIED");
  });
});

describe("thresholds and mode", () => {
  test("a threshold row shows the value in force and 'sin cambios' when it is untouched", () => {
    const markup = html(<ThresholdRow currency="EUR" value="500.00" savedMinor={50000} onChange={() => {}} />);
    expect(markup).toContain('class="pb-thr"');
    expect(markup).toContain("Vigente <b>EUR 500.00</b>");
    expect(markup).toContain("· sin cambios");
    expect(markup).not.toContain("Editado");
    expect(markup).not.toContain("pb-gauge");
  });

  test("an edited row is marked, and the USD row compares the demo charge with the threshold", () => {
    const markup = html(<ThresholdRow currency="USD" value="100" savedMinor={50000} onChange={() => {}} />);
    expect(markup).toContain("Editado");
    expect(markup).toContain("Vigente <b>USD 500.00</b>");
    expect(markup).toContain('class="pb-gauge pb-gauge--sm"');
    expect(markup).toContain('data-state="caution"');
    expect(markup).toContain("POR ENCIMA");
    expect(markup).toContain('role="meter"');
    expect(markup).toContain('aria-valuetext="Cargo de demo USD 139.99, umbral USD 100.00: por encima"');
    expect(markup).toContain("--tau:0.5");
  });

  test("a threshold above the demo charge reads 'below' and the gauge is not in caution", () => {
    const markup = html(<ThresholdRow currency="USD" value="500.00" savedMinor={50000} onChange={() => {}} />);
    expect(markup).toContain("POR DEBAJO");
    expect(markup).toContain('data-state="decided"');
  });

  test("an invalid threshold is marked invalid, with the reason, and shows no demo comparison", () => {
    const markup = html(<ThresholdRow currency="USD" value="cien" savedMinor={10000} onChange={() => {}} />);
    expect(markup).toContain('aria-invalid="true"');
    expect(markup).toContain('class="pb-help pb-help--error"');
    expect(markup).toContain("mayor que cero");
    expect(markup).not.toContain("pb-gauge");
  });

  test("the input has a label for screen readers", () => {
    expect(html(<ThresholdRow currency="COP" value="2,000,000" savedMinor={200000000} onChange={() => {}} />)).toContain('<span class="pb-sr">Umbral en COP</span>');
  });

  test("the modes are labelled 'handoff recomendado (flag)' and 'handoff requerido (block)', one checked", () => {
    const markup = html(<ModeGroup mode="block" onChange={() => {}} />);
    expect(markup).toContain('role="radiogroup"');
    expect(markup).toContain('data-mode="flag"');
    expect(markup).toContain('data-mode="block"');
    expect(markup).toContain('aria-checked="false" data-mode="flag"');
    expect(markup).toContain('aria-checked="true" data-mode="block"');
    expect(markup).toContain('handoff recomendado <span class="bo-raw">(flag)</span>');
    expect(markup).toContain('handoff requerido <span class="bo-raw">(block)</span>');
    expect(markup).toContain("No bloquea la tarjeta.");
    expect(html(<ModeGroup mode="flag" onChange={() => {}} />)).toContain("sobre el umbral se recomienda un handoff");
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

describe("the transcript", () => {
  test("shows customer, assistant and agent messages in the chat's own classes", () => {
    const data = transcript({ takeover: { active: true, since: new Date(NOW).toISOString(), agent_ref: AGENT_EMAIL }, withAgentMessage: true }, NOW);
    const markup = html(<TranscriptLog messages={data.messages} agent="agent" />);
    expect(markup).toContain('role="log"');
    expect(count(markup, "pb-msg--customer")).toBe(2);
    expect(count(markup, "pb-msg--assistant")).toBe(2);
    expect(count(markup, "pb-msg--agent")).toBe(1);
    // The customer's messages are masked at the source and shown as stored; the agent's own text is as written.
    expect(markup).toContain("[EMAIL_1]");
    expect(markup).toContain("[OTP_1]");
    expect(markup).toContain("Hola, soy Ana, del equipo de fraude.");
    expect(markup).not.toContain("[NAME_1]");
    // A human's message follows a "joined" line and is labelled.
    expect(markup).toContain('<div class="pb-sys" data-tone="joined">');
    expect(markup).toContain("agent tomó la conversación");
    expect(markup).toContain("Agente humano · agent");
  });

  test("renders a receipt block as a receipt, with masked target and the audit id", () => {
    const markup = html(<TranscriptLog messages={transcript({}, NOW).messages} agent={null} />);
    expect(markup).toContain('data-tone="receipt"');
    expect(markup).toContain("Comprobante · card.block");
    expect(markup).toContain("ACTIVE");
    expect(markup).toContain("BLOCKED");
    expect(markup).toContain("••••4821");
    expect(markup).toContain("aud_00020481");
  });

  test("a block it does not know degrades to a line, not a blank chat", () => {
    const messages = [{ role: "assistant" as const, content: "Mira esto.", blocks: [{ type: "carousel", items: [] }], created_at: new Date(NOW).toISOString() }];
    const markup = html(<TranscriptLog messages={messages} agent={null} />);
    expect(markup).toContain("Mira esto.");
    expect(markup).toContain("Bloque no mostrado (carousel)");
  });

  test("an empty transcript says so", () => {
    expect(html(<TranscriptLog messages={[]} agent={null} />)).toContain("Todavía no hay mensajes.");
  });
});

describe("the composer", () => {
  const props = { lockedReason: "locked" as const, sending: false, failed: false, outbox: null, error: null, onSend: () => {}, onRetry: () => {}, onDiscard: () => {} };

  test("is locked until the case is taken", () => {
    const markup = html(<Composer {...props} enabled={false} />);
    expect(markup).toContain("disabled");
    expect(markup).toContain('placeholder="Toma el caso para poder responder."');
    expect(html(<Composer {...props} enabled={false} lockedReason="lockedOther" />)).toContain("Otro agente tiene la conversación.");
  });

  test("once taken it is a labelled input limited to 2000 characters, and says what the customer and the assistant see", () => {
    const markup = html(<Composer {...props} enabled />);
    expect(markup).toContain('maxLength="2000"');
    expect(markup).toContain('<span class="pb-sr">Respuesta al cliente</span>');
    expect(markup).toContain("El cliente ve el texto exactamente como lo escribes.");
    expect(markup).toContain("El asistente no lo ve.");
    expect(markup).toContain("Escribe solo lo que el cliente necesita.");
    // The text is not masked any more, so the note must not say that it is.
    expect(markup).not.toContain("enmascar");
    expect(markup).not.toContain('placeholder="Toma el caso');
  });

  test("a message that was not sent stays visible with a retry that resends the same one", () => {
    const markup = html(<Composer {...props} enabled failed outbox={{ text: "Hola", client_message_id: "msg_123456789" }} error="turnInProgress" />);
    expect(markup).toContain("No enviado");
    expect(markup).toContain("Hola");
    expect(markup).toContain("Un turno del cliente sigue en curso. Reintenta: se reenvía el mismo mensaje.");
    expect(markup).toContain("Reintentar el mismo mensaje");
    expect(markup).toContain("Descartar");
  });
});

describe("metrics tables", () => {
  const data = metrics(24, NOW);

  test("tool calls: an action, its decision in words and as the enum, the reason, the count and the share", () => {
    const markup = html(<ToolCallsTable rows={data.tool_calls} />);
    expect(markup).toContain('role="table"');
    expect(count(markup, 'class="pb-qrow"')).toBe(data.tool_calls.length);
    expect(markup).toContain("STATE_NOT_ALLOWED");
    expect(markup).toContain("Estado no permitido");
    expect(markup).toContain("Rechazada");
    expect(markup).toContain("Permitida");
    expect(markup).toContain('data-state="blocked"'); // the one error
    expect(markup).toContain('data-state="caution"'); // refusals
    expect(markup).toContain('data-state="decided"'); // allowed
    // Grouped by action.
    expect(markup.indexOf("account.get_summary")).toBeLessThan(markup.indexOf("card.block"));
    expect(markup.indexOf("card.block")).toBeLessThan(markup.indexOf("otp.send"));
  });

  test("handoff distributions list every value of the enum, with 0 where the API left it out", () => {
    const markup = html(<HandoffTables handoffs={data.handoffs} />);
    for (const value of ["QUEUED", "ASSIGNED", "PENDING", "URGENT", "HIGH", "NORMAL", "LOW", "FRAUD_OPERATIONS", "CUSTOMER_SUPPORT", "DISPUTES"]) {
      expect(markup).toContain(value);
    }
    expect(markup).toContain("Por estado");
    expect(markup).toContain("Por prioridad");
    expect(markup).toContain("Por departamento");
    expect(markup).toMatch(/PENDING<\/span><\/span><\/span><span role="cell" data-col="count">0</);
    expect(markup).toContain("25%"); // 3 of 12
  });
});
