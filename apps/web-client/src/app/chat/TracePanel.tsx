// Detective mode's view (ADR-0019): one turn as the system ran it, a tab of the demo panel, beside the chat or, with no
// room for it, in the chat panel's place. Two views of the
// same steps: a list where each step opens in place, and a timeline of bars on the turn's clock with the picked
// step under it. A stepper moves between the turns that came with a trace. Numbers and the system's own names,
// few words. The header (title, the button back to the chat) and the panel's tabs belong to the dock. Props only, no machine, so it
// renders on the server in the tests exactly as it does in the page. Every value in a trace is masked as the
// LLM saw it.

import type { TraceEvent, TurnTrace } from "@pattern-blue/contracts";
import { useId, useState, type CSSProperties, type ReactNode } from "react";
import { format, type Dictionary } from "../../i18n";
import { Icon } from "../ui/Icon";
import { conversationTotal, defaultStep, formatMs, formatUsd, prettyJson, shortModel, splitPlaceholders, summarize, turnNeighbours, type TracedTurn } from "./trace-model";

export type TraceView = "steps" | "timeline";

const STATUS_TONE: Record<TraceEvent["status"], string> = { ok: "success", refused: "warning", error: "danger", skipped: "neutral" };

export interface TracePanelProps {
  dict: Dictionary;
  /** The replies that came with a trace, oldest first. */
  turns: readonly TracedTurn[];
  /** Every reply of the conversation, traced or not: the "de total" of the stepper. */
  total: number;
  selectedId: string | null;
  view: TraceView;
  onSelect: (id: string) => void;
  onView: (view: TraceView) => void;
}

export function TracePanel({ dict, turns, total, selectedId, view, onSelect, onView }: TracePanelProps) {
  const t = dict.chat.detective;
  const turn = turns.find((item) => item.id === selectedId) ?? turns[turns.length - 1] ?? null;
  if (!turn) {
    return (
      <div className="pb-trace pb-trace--inpanel">
        <div className="pb-trace__body">
          <p className="pb-trace__empty">{t.empty}</p>
        </div>
      </div>
    );
  }
  const { prev, next } = turnNeighbours(turns, turn.id);
  const sum = summarize(turn.trace);
  const all = conversationTotal(turns);
  return (
    <div className="pb-trace pb-trace--inpanel">
      <div className="pb-trace__head">
        <div className="pb-trace__nav">
          <span className="pb-trace__stepper" role="group" aria-label={t.turns}>
            <button className="pb-btn pb-btn--ghost pb-btn--icon" type="button" aria-label={t.prev} aria-disabled={prev ? undefined : true} data-trace-prev onClick={() => prev && onSelect(prev.id)}>
              <i className="pb-ico pb-ico--arrow pb-ico--prev" aria-hidden="true" />
            </button>
            <b aria-live="polite">{format(t.turnOf, { n: turn.n, total: Math.max(total, turn.n) })}</b>
            <button className="pb-btn pb-btn--ghost pb-btn--icon" type="button" aria-label={t.next} aria-disabled={next ? undefined : true} data-trace-next onClick={() => next && onSelect(next.id)}>
              <Icon name="arrow" />
            </button>
          </span>
          <div className="pb-tabs pb-trace__views" role="radiogroup" aria-label={t.views}>
            {(["steps", "timeline"] as const).map((name) => (
              <button key={name} type="button" className="pb-tab" role="radio" aria-checked={view === name} data-trace-view={name} onClick={() => onView(name)}>
                {t[name]}
              </button>
            ))}
          </div>
        </div>
        <dl className="pb-trace__totals">
          <dt>{t.turnLabel}</dt>
          <dd>
            <span>{formatMs(turn.trace.total_ms)}</span>
            <span>LLM {formatMs(sum.llmMs)}</span>
            <span>{sum.tokens} tok</span>
            <span>{formatUsd(sum.costUsd)}</span>
          </dd>
          <dt>{t.conversationLabel}</dt>
          <dd>
            <span>{all.tokens} tok</span>
            <span>{formatUsd(all.costUsd)}</span>
          </dd>
        </dl>
        <Spark trace={turn.trace} />
      </div>
      {/* A new turn or view starts at the top. */}
      <div className="pb-trace__body" key={`${turn.id}:${view}`}>
        {view === "steps" ? <StepList dict={dict} trace={turn.trace} /> : <Timeline dict={dict} trace={turn.trace} />}
      </div>
    </div>
  );
}

/**
 * Under each reply that came with a trace, while the environment offers the mode: an action of the system with the
 * icon, "Ver detective" and the turn's time. It opens that turn (beside the chat, or in place of it when there is no room).
 */
export function TraceOpen({ dict, trace, onOpen }: { dict: Dictionary; trace: TurnTrace; onOpen?: () => void }) {
  const time = formatMs(trace.total_ms);
  return (
    <button className="pb-action pb-trace-open" type="button" aria-label={format(dict.chat.detective.open, { time })} data-trace-open onClick={onOpen}>
      <Icon name="detective" />
      <span>
        {dict.chat.detective.view} <span className="pb-trace-open__time">· {time}</span>
      </span>
      <Icon name="arrow" />
    </button>
  );
}

/**
 * Where the time of a turn went, one segment per step, in the step kind's tone. The segments are laid end to end
 * from the left (`--x` to `--x2`, shares of the turn): the stylesheet puts each boundary on a cell, so they never
 * add up to more than the bar.
 */
function Spark({ trace }: { trace: TurnTrace }) {
  const total = trace.total_ms || 1;
  let elapsed = 0;
  return (
    <span className="pb-trace-spark" aria-hidden="true">
      {trace.events
        .filter((event) => event.duration_ms)
        .map((event) => {
          const from = Math.min(100, (elapsed / total) * 100);
          elapsed += event.duration_ms ?? 0;
          const to = Math.min(100, (elapsed / total) * 100);
          return (
            <span
              key={event.seq}
              data-kind={event.kind}
              style={{ "--x": `${from}%`, "--x2": `${to}%`, "--w": `${to - from}%` } as CSSProperties}
            />
          );
        })}
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

/** `LLM #2`, a tool by its own name (`card.block`), any other step by its kind. */
function StepName({ dict, event }: { dict: Dictionary; event: TraceEvent }) {
  if (event.llm_call) return <span>{`LLM #${event.llm_call.round}`}</span>;
  if (event.kind === "tool_call" || event.kind === "engine_handoff") return <code className="pb-trace-name">{event.tool_call?.tool ?? event.label}</code>;
  return <span>{dict.chat.detective.kinds[event.kind]}</span>;
}

/** The one line under a step's name: what it decided, in the system's own words. */
function stepHint(event: TraceEvent): string {
  if (event.encoder) return event.encoder.intent && event.encoder.confidence !== null ? `${event.encoder.intent} · ${(event.encoder.confidence * 100).toFixed(0)}%` : "—";
  if (event.masking) return event.masking.placeholders.join(" ");
  if (event.llm_call) return `${event.llm_call.total_tokens ?? "?"} tok → ${event.llm_call.response_tool_calls.map((call) => call.name).join(", ") || "text"}`;
  if (event.tool_call) return event.tool_call.reason_code ?? event.tool_call.flow_state ?? "";
  return event.note ?? "";
}

/** Only a step that went wrong has a chip: an ok step says nothing, and neither does one that was skipped (the engine skips a step when there was nothing to do; its line says so). */
function StatusChip({ dict, status }: { dict: Dictionary; status: TraceEvent["status"] }) {
  if (status === "ok" || status === "skipped") return null;
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

const line = (...parts: (string | null | false | undefined)[]) => parts.filter(Boolean).join(" · ");

/** What one step did: a line at most, the masked values, the long parts folded. */
function StepDetail({ dict, event }: { dict: Dictionary; event: TraceEvent }) {
  const d = dict.chat.detective.detail;
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
          {(masking.failed || masking.regex_only) && <p className="pb-trace-detail__line">{masking.failed ? d.maskFailed : d.regexOnly}</p>}
        </>
      )}
      {llm && (
        <>
          <p className="pb-trace-detail__line">
            {line(shortModel(llm.model), `${llm.prompt_tokens ?? "?"} → ${llm.completion_tokens ?? "?"} tok`, llm.cost_usd !== null && formatUsd(llm.cost_usd), llm.cached && "replay")}
          </p>
          {llm.response_content && <Code text={llm.response_content} />}
          {llm.response_tool_calls.map((call) => (
            <Code key={call.call_id} text={`${call.name}(${prettyJson(call.arguments)})`} />
          ))}
          <More summary={`Prompt (${llm.messages_from > 0 ? "+" : ""}${llm.messages.length})`}>
            {llm.messages.map((message, index) => (
              <div key={index} className="pb-trace-msg" data-role={message.role}>
                <span className="pb-trace-msg__role">{message.role}</span>
                {message.role === "system" && message.content ? (
                  <More summary={`${message.content.slice(0, 60)}…`}>
                    <Code text={message.content} />
                  </More>
                ) : (
                  message.content && <Code text={message.content} json={message.role === "tool"} />
                )}
                {message.tool_calls && <Code text={message.tool_calls} json />}
              </div>
            ))}
          </More>
          <More summary={format(d.tools, { n: llm.tools_offered.length })}>
            <Tags items={llm.tools_offered} />
          </More>
        </>
      )}
      {tool && (
        <>
          <p className="pb-trace-detail__line">
            {line(tool.executed ? "banking-core" : d.engine, tool.reason_code, tool.flow_state && [tool.flow_state, ...tool.flow_next].join(" → "))}
          </p>
          {tool.arguments && <Code text={tool.arguments} json />}
          {tool.feedback && (
            <More summary={d.result}>
              <Code text={tool.feedback} json />
            </More>
          )}
        </>
      )}
      {blocks && (
        <p className="pb-trace-detail__line">
          {line(blocks.kept.join(", ") || "—", ...blocks.dropped.map((type) => `−${type}`), blocks.fallback && d.fallback)}
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
          <p className="pb-trace-detail__line">—</p>
        ))}
    </div>
  );
}
