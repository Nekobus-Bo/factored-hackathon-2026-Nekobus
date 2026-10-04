// Detective mode's panel (ADR-0019): one turn as the system ran it, beside the chat, with its own scroll.
// Two views of the same steps: a list where each step opens in place, and a timeline of bars on the turn's
// clock with the picked step under it. Below 900px there is no room beside the chat, so the panel covers it
// and "Volver al chat" goes back. Props only, no machine, so it renders on the server in the tests exactly
// as it does in the page. Every value in a trace is masked as the LLM saw it.

import type { TraceEvent, TurnTrace } from "@pattern-blue/contracts";
import { useId, useState, type CSSProperties, type ReactNode, type Ref } from "react";
import { format, type Dictionary } from "../../i18n";
import { Icon } from "../ui/Icon";
import { defaultStep, formatMs, formatUsd, prettyJson, splitPlaceholders, summarize, type TracedTurn } from "./trace-model";

export type TraceView = "steps" | "timeline";
export type DockPane = "chat" | "trace";

const STATUS_TONE: Record<TraceEvent["status"], string> = { ok: "success", refused: "warning", error: "danger", skipped: "neutral" };

export interface TracePanelProps {
  dict: Dictionary;
  turns: readonly TracedTurn[];
  selectedId: string | null;
  view: TraceView;
  /** Below 900px the panel covers the chat while this is "trace". */
  pane: DockPane;
  onSelect: (id: string) => void;
  onView: (view: TraceView) => void;
  onBack: () => void;
  backRef?: Ref<HTMLButtonElement>;
}

export function TracePanel({ dict, turns, selectedId, view, pane, onSelect, onView, onBack, backRef }: TracePanelProps) {
  const t = dict.chat.detective;
  const turn = turns.find((item) => item.id === selectedId) ?? turns[turns.length - 1] ?? null;
  return (
    <aside
      className="pb-trace pb-dock__trace"
      id="dock-trace"
      aria-label={t.panel}
      data-pane={pane}
      onKeyDown={(event) => {
        if (event.key === "Escape") onBack();
      }}
    >
      <header className="pb-trace__head">
        <div className="pb-trace__bar">
          <button ref={backRef} className="pb-btn pb-btn--ghost pb-btn--sm pb-trace__back" type="button" onClick={onBack}>
            <Icon name="chat" />
            {t.back}
          </button>
          <h2 className="pb-trace__title">
            <Icon name="search" /> {t.title}
          </h2>
          <div className="pb-tabs pb-trace__views" role="radiogroup" aria-label={t.views}>
            {(["steps", "timeline"] as const).map((name) => (
              <button key={name} type="button" className="pb-tab" role="radio" aria-checked={view === name} data-trace-view={name} onClick={() => onView(name)}>
                {t[name]}
              </button>
            ))}
          </div>
        </div>
        {turns.length > 0 && (
          <div className="pb-trace__turns" role="radiogroup" aria-label={t.turns}>
            {turns.map((item) => (
              <button
                key={item.id}
                type="button"
                className="pb-trace__turn"
                role="radio"
                aria-checked={item.id === turn?.id}
                data-trace-turn={item.id}
                onClick={() => onSelect(item.id)}
              >
                <b>{format(t.turn, { n: item.n })}</b>
                {formatMs(item.trace.total_ms)}
              </button>
            ))}
          </div>
        )}
        {turn && <TurnSummary dict={dict} turn={turn} />}
      </header>
      {/* A new turn or view starts at the top. */}
      <div className="pb-trace__body" key={`${turn?.id ?? "none"}:${view}`}>
        {turn ? (
          view === "steps" ? (
            <StepList key={turn.id} dict={dict} trace={turn.trace} />
          ) : (
            <Timeline key={turn.id} dict={dict} trace={turn.trace} />
          )
        ) : (
          <p className="pb-trace__empty">{t.empty}</p>
        )}
      </div>
    </aside>
  );
}

/** Under each reply while detective mode is on: the turn in one line; it opens the turn in the panel. */
export function TraceStrip({ dict, trace, selected, onPick }: { dict: Dictionary; trace: TurnTrace; selected: boolean; onPick?: () => void }) {
  const t = dict.chat.detective;
  const s = summarize(trace);
  return (
    <button className="pb-trace-strip" type="button" aria-current={selected ? "true" : undefined} aria-controls="dock-trace" data-detective onClick={onPick}>
      <span className="pb-trace-strip__line">
        <Icon name="search" />
        <b>{formatMs(trace.total_ms)}</b>
        <span>{format(t.strip, { steps: s.steps, llm: s.llm, tools: s.tools })}</span>
        <span className="pb-sr">{t.open}</span>
      </span>
      <Spark trace={trace} />
    </button>
  );
}

function TurnSummary({ dict, turn }: { dict: Dictionary; turn: TracedTurn }) {
  const t = dict.chat.detective.stats;
  const s = summarize(turn.trace);
  return (
    <>
      {turn.quote && <p className="pb-trace__quote">{turn.quote}</p>}
      <p className="pb-trace__stats">
        <span>
          <b>{formatMs(turn.trace.total_ms)}</b> {t.total}
        </span>
        <span>
          <b>{formatMs(s.llmMs)}</b> {t.llm}
        </span>
        <span>
          <b>{s.steps}</b> {t.steps}
        </span>
        <span>
          <b>{s.tools}</b> {t.tools}
        </span>
        <span>
          <b>{s.tokens}</b> {t.tokens}
        </span>
        <span>
          <b>{formatUsd(s.costUsd)}</b>
        </span>
      </p>
      <Spark trace={turn.trace} />
    </>
  );
}

/** Where the time of a turn went, one segment per step, in the step kind's color. */
function Spark({ trace }: { trace: TurnTrace }) {
  const total = trace.total_ms || 1;
  return (
    <span className="pb-trace-spark" aria-hidden="true">
      {trace.events
        .filter((event) => event.duration_ms)
        .map((event) => (
          <span key={event.seq} data-kind={event.kind} style={{ "--w": `${Math.max(0.6, ((event.duration_ms ?? 0) / total) * 100)}%` } as CSSProperties} />
        ))}
    </span>
  );
}

function StepList({ dict, trace }: { dict: Dictionary; trace: TurnTrace }) {
  const [open, setOpen] = useState<number | null>(null);
  const base = useId();
  return (
    <ol className="pb-trace-steps">
      {trace.events.map((event) => {
        const expanded = open === event.seq;
        const id = `${base}-${event.seq}`;
        return (
          <li key={event.seq}>
            <button
              className="pb-trace-step"
              type="button"
              aria-expanded={expanded}
              aria-controls={id}
              data-trace-step={event.seq}
              onClick={() => setOpen(expanded ? null : event.seq)}
            >
              <span className="pb-trace-dot" data-kind={event.kind} />
              <span className="pb-trace-step__name">
                <StepName dict={dict} event={event} />
                <small>{stepHint(event)}</small>
              </span>
              <span className="pb-trace-step__ms">{formatMs(event.duration_ms)}</span>
              <StatusChip dict={dict} status={event.status} />
            </button>
            <div className="pb-trace-step__detail" id={id} hidden={!expanded}>
              {expanded && <StepDetail dict={dict} event={event} />}
            </div>
          </li>
        );
      })}
    </ol>
  );
}

function Timeline({ dict, trace }: { dict: Dictionary; trace: TurnTrace }) {
  const [picked, setPicked] = useState<number | null>(defaultStep(trace)?.seq ?? null);
  const total = Math.max(trace.total_ms, 1);
  const step = trace.events.find((event) => event.seq === picked) ?? null;
  return (
    <>
      <div className="pb-trace-wf">
        <div className="pb-trace-wf__axis" aria-hidden="true">
          <span />
          <span>
            <span>0</span>
            <span>{formatMs(total / 2)}</span>
            <span>{formatMs(total)}</span>
          </span>
          <span />
        </div>
        {trace.events.map((event) => (
          <button
            key={event.seq}
            className="pb-trace-wf__row"
            type="button"
            aria-pressed={event.seq === picked}
            data-trace-step={event.seq}
            onClick={() => setPicked(event.seq)}
          >
            <span className="pb-trace-wf__name">
              <span className="pb-trace-dot" data-kind={event.kind} />
              <StepName dict={dict} event={event} />
            </span>
            <span className="pb-trace-wf__track">
              <span
                className="pb-trace-wf__bar"
                data-kind={event.kind}
                style={{ "--x": `${(event.start_ms / total) * 100}%`, "--w": `${((event.duration_ms ?? 0) / total) * 100}%` } as CSSProperties}
              />
            </span>
            <span className="pb-trace-step__ms">{formatMs(event.duration_ms)}</span>
          </button>
        ))}
      </div>
      {step && (
        <section className="pb-trace-wf__detail" aria-label={dict.chat.detective.kinds[step.kind]}>
          <h3 className="pb-trace-wf__head">
            <span className="pb-trace-dot" data-kind={step.kind} />
            <StepName dict={dict} event={step} />
            <StatusChip dict={dict} status={step.status} />
            <span className="pb-trace-step__ms">{formatMs(step.duration_ms)}</span>
          </h3>
          <StepDetail dict={dict} event={step} />
        </section>
      )}
    </>
  );
}

/** The kind, plus which one: `LLM #2`, `Herramienta card.block`. */
function StepName({ dict, event }: { dict: Dictionary; event: TraceEvent }) {
  const kind = dict.chat.detective.kinds[event.kind];
  if (event.llm_call) return <span>{`${kind} #${event.llm_call.round}`}</span>;
  const tool = event.kind === "tool_call" || event.kind === "engine_handoff";
  return (
    <span>
      {kind}
      {tool && <span className="pb-tag">{event.tool_call?.tool ?? event.label}</span>}
    </span>
  );
}

/** The one line under a step's name: what it decided, in the system's own words. */
function stepHint(event: TraceEvent): string {
  if (event.encoder) return event.encoder.intent && event.encoder.confidence !== null ? `${event.encoder.intent} · ${(event.encoder.confidence * 100).toFixed(0)}%` : "—";
  if (event.masking) return event.masking.placeholders.join(" ");
  if (event.llm_call) return `${event.llm_call.total_tokens ?? "?"} tok → ${event.llm_call.response_tool_calls.map((call) => call.name).join(", ") || "text"}`;
  if (event.tool_call) return event.tool_call.reason_code ?? event.tool_call.flow_state ?? "";
  return event.note ?? "";
}

function StatusChip({ dict, status }: { dict: Dictionary; status: TraceEvent["status"] }) {
  return (
    <span className="pb-chip" data-tone={STATUS_TONE[status]}>
      {dict.chat.detective.status[status]}
    </span>
  );
}

/** A masked text with its placeholders marked. */
function Masked({ text }: { text: string }) {
  return (
    <>
      {splitPlaceholders(text).map((part, index) =>
        part.placeholder ? (
          <mark key={index} className="pb-trace-ph">
            {part.text}
          </mark>
        ) : (
          part.text
        ),
      )}
    </>
  );
}

function Code({ text, json = false }: { text: string; json?: boolean }) {
  return (
    <pre className="pb-trace-code">
      <Masked text={json ? prettyJson(text) : text} />
    </pre>
  );
}

function Tags({ items }: { items: readonly string[] }) {
  return (
    <span className="pb-trace-tags">
      {items.map((item) => (
        <span key={item} className="pb-tag">
          {item}
        </span>
      ))}
    </span>
  );
}

function More({ summary, children }: { summary: string; children: ReactNode }) {
  return (
    <details className="pb-trace-more">
      <summary>{summary}</summary>
      {children}
    </details>
  );
}

/** What one step did, in as few lines as it takes; the long parts fold. */
function StepDetail({ dict, event }: { dict: Dictionary; event: TraceEvent }) {
  const d = dict.chat.detective.detail;
  const line = (...parts: (string | null | false | undefined)[]) => parts.filter(Boolean).join(" · ");
  const { encoder, masking, llm_call: llm, tool_call: tool, blocks, decisions } = event;
  return (
    <div className="pb-trace-detail">
      {event.note && <p className="pb-trace-detail__line">{event.note}</p>}
      {encoder &&
        (encoder.available ? (
          <>
            {encoder.confidence !== null && (
              <div className="pb-gauge pb-gauge--sm" data-state={encoder.abstain ? "abstained" : "decided"} style={{ "--on": Math.round(encoder.confidence * 20) } as CSSProperties}>
                <div className="pb-gauge__head">
                  <span className="pb-gauge__name">{encoder.intent ?? "—"}</span>
                  <span className="pb-gauge__val">
                    {(encoder.confidence * 100).toFixed(1)}
                    <small>%</small>
                  </span>
                </div>
                <div className="pb-gauge__track" aria-hidden="true">
                  <div className="pb-gauge__fill" />
                </div>
              </div>
            )}
            <p className="pb-trace-detail__line">{line(encoder.model_id, encoder.server_latency_ms !== null && format(d.server, { time: formatMs(encoder.server_latency_ms) }))}</p>
            {(encoder.pii_spans.length > 0 || encoder.slots.length > 0) && <Tags items={[...encoder.pii_spans.map((span) => `${span.type} × ${span.count}`), ...encoder.slots]} />}
            {encoder.decision_points.length > 0 && (
              <table className="pb-trace-table">
                <tbody>
                  {encoder.decision_points.map((point) => (
                    <tr key={point.dp_id}>
                      <td>{point.dp_id}</td>
                      <td>{point.label ?? point.outcome}</td>
                      <td>{point.confidence.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </>
        ) : (
          <p className="pb-trace-detail__line">{d.unavailable}</p>
        ))}
      {masking && (
        <>
          {masking.masked_text !== null && <Code text={masking.masked_text} />}
          <p className="pb-trace-detail__line">
            {masking.failed ? d.maskFailed : masking.placeholders.length > 0 ? `${d.minted}: ${masking.placeholders.join(" ")}` : d.noPii}
            {masking.regex_only && ` · ${d.regexOnly}`}
          </p>
        </>
      )}
      {llm && (
        <>
          <p className="pb-trace-detail__line">
            {line(
              llm.model,
              `${llm.prompt_tokens ?? "?"} → ${llm.completion_tokens ?? "?"} tok`,
              llm.cost_usd !== null && formatUsd(llm.cost_usd),
              llm.cached ? d.replay : d.live,
            )}
          </p>
          {llm.response_content && <Code text={llm.response_content} />}
          {llm.response_tool_calls.map((call) => (
            <Code key={call.call_id} text={`${call.name}(${prettyJson(call.arguments)})`} />
          ))}
          <More summary={format(d.prompt, { n: llm.messages.length })}>
            {llm.messages_from > 0 && <p className="pb-trace-detail__line">{format(d.promptFrom, { n: llm.messages_from + 1 })}</p>}
            {llm.messages.map((message, index) => (
              <div key={index} className="pb-trace-msg" data-role={message.role}>
                <span className="pb-trace-msg__role">{message.role}</span>
                {message.role === "system" && message.content ? (
                  <More summary={format(d.chars, { n: message.content.length })}>
                    <Code text={message.content} />
                  </More>
                ) : (
                  message.content && <Code text={message.content} json={message.role === "tool"} />
                )}
                {message.tool_calls && <Code text={message.tool_calls} json />}
              </div>
            ))}
          </More>
          <More summary={format(d.offered, { n: llm.tools_offered.length })}>
            <Tags items={llm.tools_offered} />
          </More>
        </>
      )}
      {tool && (
        <>
          <p className="pb-trace-detail__line">
            {line(
              tool.executed ? d.executed : (tool.local_reason ?? d.notExecuted),
              tool.reason_code,
              tool.flow_state && `→ ${tool.flow_state}`,
              tool.flow_next.length > 0 && `${d.next}: ${tool.flow_next.join(", ")}`,
            )}
          </p>
          {tool.arguments && <Code text={tool.arguments} json />}
          {tool.feedback && (
            <More summary={d.feedback}>
              <Code text={tool.feedback} json />
            </More>
          )}
        </>
      )}
      {blocks && (
        <p className="pb-trace-detail__line">
          {line(
            `${d.sent}: ${blocks.kept.join(", ") || "—"}`,
            blocks.dropped.length > 0 && `${d.dropped}: ${blocks.dropped.join(", ")}`,
            blocks.internal_lines_withheld > 0 && format(d.withheld, { n: blocks.internal_lines_withheld }),
            blocks.fallback && d.fallback,
          )}
        </p>
      )}
      {decisions &&
        (decisions.decisions.length > 0 ? (
          <table className="pb-trace-table">
            <tbody>
              {decisions.decisions.map((row) => (
                <tr key={row.dp_id}>
                  <td>{row.dp_id}</td>
                  <td>{row.mode}</td>
                  <td>{row.label ?? row.unavailable_reason ?? row.outcome}</td>
                  <td>{row.confidence.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        ) : (
          <p className="pb-trace-detail__line">{d.noDecisions}</p>
        ))}
    </div>
  );
}
