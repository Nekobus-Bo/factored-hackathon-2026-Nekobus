// PolicyControl (design system: PolicyControl, as changed by the declutter review of 2026-10-02): the
// amount threshold per currency, the handoff mode and the tools by state as one matrix. Presentational:
// the guardrails machine owns the draft and the rules.
//
// Deviations from the component's README:
//   * no "Semilla" (the .env seed): `GET /v1/admin/policy-config` does not return it. A row shows its old
//     value only once it is edited;
//   * the API needs a threshold greater than zero (the README says "non-negative");
//   * the tools are one table with the states as columns, named once, instead of a block per tool.

import type { AmountMode, VerificationState } from "@pattern-blue/contracts";
import { Switch } from "@ark-ui/react/switch";
import type { CSSProperties } from "react";
import { FSM_ORDER } from "../machines/policy-draft";
import type { Refusal } from "../machines/guardrails";
import { useI18n } from "./context";
import { money, parseMajor } from "./format";
import { Alert, Icon, StateChip } from "./ui";

/** The English demo customer's disputed charge (docs/runbook.md, section 7): USD 139.99, on a 0 to 200 scale. */
export const DEMO_CHARGE_MINOR = 13999;
const DEMO_SCALE_MINOR = 20000;

// --- Thresholds -----------------------------------------------------------------------------------------

export function ThresholdRow({
  currency,
  value,
  savedMinor,
  onChange,
}: {
  currency: string;
  value: string;
  /** The threshold in force, in minor units. */
  savedMinor: number | undefined;
  onChange: (value: string) => void;
}) {
  const { t } = useI18n();
  const minor = parseMajor(value);
  const invalid = minor === null;
  const edited = !invalid && minor !== savedMinor;
  const inputId = `thr-${currency}`;
  const showDemo = currency === "USD" && !invalid;
  const above = showDemo && DEMO_CHARGE_MINOR > (minor ?? 0);
  const thresholdText = minor === null ? "" : money(minor, currency);
  const demoText = t(above ? "guardrails.thresholds.demoAbove" : "guardrails.thresholds.demoBelow", {
    amount: money(DEMO_CHARGE_MINOR, "USD"),
    threshold: thresholdText,
  });

  return (
    <div className="pb-thr">
      <span className="pb-thr__cur">{currency}</span>
      <div>
        <label className="pb-field pb-field--mono" data-invalid={invalid ? "" : undefined}>
          <span className="pb-sr">{t("guardrails.thresholds.label", { currency })}</span>
          <input
            id={inputId}
            type="text"
            inputMode="decimal"
            autoComplete="off"
            value={value}
            aria-invalid={invalid}
            aria-describedby={invalid ? `${inputId}-error` : undefined}
            onChange={(event) => onChange(event.target.value)}
          />
        </label>
        {invalid && (
          <p className="pb-help pb-help--error" id={`${inputId}-error`}>
            <Icon name="warning" />
            {t("guardrails.thresholds.invalid")}
          </p>
        )}
      </div>
      <div className="pb-thr__side">
        {edited && (
          <div className="pb-thr__seed">
            <span className="pb-chip" data-tone="warning">
              <Icon name="warning" />
              {t("guardrails.thresholds.edited")}
            </span>
            <span>{t("guardrails.thresholds.before", { amount: savedMinor === undefined ? t("common.empty") : money(savedMinor, currency) })}</span>
          </div>
        )}
        {showDemo && (
          <div className="pb-thr__demo">
            <span>{t(above ? "guardrails.thresholds.demoAboveLine" : "guardrails.thresholds.demoBelowLine", { amount: money(DEMO_CHARGE_MINOR, "USD") })}</span>
            <div
              className="pb-gauge pb-gauge--sm"
              data-state={above ? "caution" : "decided"}
              style={{ "--n": 20, "--on": Math.round((DEMO_CHARGE_MINOR / DEMO_SCALE_MINOR) * 20), "--tau": Math.min(1, (minor ?? 0) / DEMO_SCALE_MINOR) } as CSSProperties}
              role="meter"
              aria-label={t("guardrails.thresholds.demoMeter")}
              aria-valuemin={0}
              aria-valuemax={DEMO_SCALE_MINOR / 100}
              aria-valuenow={DEMO_CHARGE_MINOR / 100}
              aria-valuetext={demoText}
            >
              <div className="pb-gauge__track">
                <div className="pb-gauge__fill" />
                <span className="pb-gauge__tau" />
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// --- Mode -----------------------------------------------------------------------------------------------

const MODES: readonly AmountMode[] = ["flag", "block"];

export function ModeGroup({ mode, onChange }: { mode: AmountMode; onChange: (mode: AmountMode) => void }) {
  const { t } = useI18n();
  return (
    <>
      <fieldset className="pb-modes bo-modes" role="radiogroup" aria-describedby="mode-help">
        <legend className="pb-sr">{t("guardrails.mode.label")}</legend>
        {MODES.map((value) => (
          <button key={value} type="button" className="pb-btn pb-btn--sm" role="radio" aria-checked={mode === value} data-mode={value} title={value} onClick={() => onChange(value)}>
            {t(value === "flag" ? "guardrails.mode.flagLabel" : "guardrails.mode.blockLabel")}
          </button>
        ))}
      </fieldset>
      <p className="pb-t-small bo-help" id="mode-help">
        {t(mode === "flag" ? "guardrails.mode.flagHelp" : "guardrails.mode.blockHelp")}
      </p>
    </>
  );
}

// --- Tool by state matrix -------------------------------------------------------------------------------

/** The three kinds of cell, shown instead of described. */
export function MatrixLegend() {
  const { t } = useI18n();
  return (
    <p className="pb-legend">
      <span>
        <span className="pb-mx__cell" role="img" aria-checked="true" aria-label={t("guardrails.tools.legendOn")}>
          <Icon name="check" />
        </span>
        {t("guardrails.tools.legendOn")}
      </span>
      <span>
        <span className="pb-mx__cell" role="img" aria-checked="false" aria-label={t("guardrails.tools.legendOff")}>
          <Icon name="check" />
        </span>
        {t("guardrails.tools.legendOff")}
      </span>
      <span>
        <span className="pb-mx__off" aria-hidden="true">
          ·
        </span>
        {t("guardrails.tools.legendOutside")}
      </span>
    </p>
  );
}

/**
 * The tools by state, one row per tool: a cell per state the code permits (on or off), a dot for a state
 * outside the code floor (nothing to click), and the tool's switch.
 */
export function ToolMatrix({
  tools,
  floorOf,
  enabled,
  onCell,
  onMaster,
}: {
  tools: readonly string[];
  floorOf: (tool: string) => readonly VerificationState[];
  enabled: (tool: string) => readonly VerificationState[];
  onCell: (tool: string, state: VerificationState) => void;
  onMaster: (tool: string) => void;
}) {
  const { t, note } = useI18n();
  return (
    <div className="pb-mx">
      <table>
        <thead>
          <tr>
            <th scope="col">{t("guardrails.tools.colTool")}</th>
            {FSM_ORDER.map((state) => (
              <th key={state} scope="col">
                <StateChip state={state} words />
              </th>
            ))}
            <th scope="col">{t("guardrails.tools.colActive")}</th>
          </tr>
        </thead>
        <tbody>
          {tools.map((tool) => {
            const floor = floorOf(tool);
            const on = enabled(tool);
            const nameId = `tool-${tool.replaceAll(".", "-")}`;
            const toolNote = note(tool);
            return (
              <tr key={tool} data-tool={tool}>
                <td>
                  <span className="pb-mx__tool">
                    <b id={nameId}>{tool}</b>
                    {toolNote && <span>{toolNote}</span>}
                  </span>
                </td>
                {FSM_ORDER.map((state) => {
                  const stateWord = t(`enums.state.${state}`);
                  return (
                    <td key={state}>
                      {floor.includes(state) ? (
                        <button
                          type="button"
                          className="pb-mx__cell"
                          role="switch"
                          aria-checked={on.includes(state)}
                          aria-label={t("guardrails.tools.cell", { tool, state: stateWord })}
                          data-fsm={state}
                          onClick={() => onCell(tool, state)}
                        >
                          <Icon name="check" />
                        </button>
                      ) : (
                        <span className="pb-mx__off" role="img" aria-label={t("guardrails.tools.outsideFloor", { state: stateWord })} data-fsm={state}>
                          ·
                        </span>
                      )}
                    </td>
                  );
                })}
                <td>
                  <span className="pb-mx__ctl">
                    <Switch.Root checked={on.length > 0} onCheckedChange={() => onMaster(tool)}>
                      <Switch.Control className="pb-switch">
                        <Switch.Thumb className="pb-switch__thumb" />
                      </Switch.Control>
                      <Switch.HiddenInput aria-labelledby={nameId} />
                    </Switch.Root>
                  </span>
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

/** The caution banner with the hazard stripe: a click outside the floor, or the API's own 422. */
export function RefusalBanner({ refusal, onDismiss }: { refusal: Refusal; onDismiss: () => void }) {
  const { t } = useI18n();
  const dismiss = (
    <button type="button" className="pb-btn pb-btn--ghost pb-btn--icon pb-btn--sm" aria-label={t("guardrails.tools.dismiss")} onClick={onDismiss}>
      <Icon name="x" />
    </button>
  );
  if (refusal.source === "local") {
    return (
      <Alert
        id="refusal"
        tone="caution"
        stripe
        eyebrow={t("guardrails.tools.refusalEyebrow")}
        hint={t("guardrails.tools.refusalHint", { floor: refusal.floor.map((state) => t(`enums.state.${state}`)).join(", ") })}
        action={dismiss}
      >
        {t("guardrails.tools.refusalText", { tool: refusal.tool, state: t(`enums.state.${refusal.state}`) })}
      </Alert>
    );
  }
  return (
    <Alert id="refusal" tone="caution" stripe eyebrow={t("guardrails.tools.refusalEyebrow")} hint={refusal.messages.join(" ")} action={dismiss}>
      {t("guardrails.tools.refusalApi")}
    </Alert>
  );
}

