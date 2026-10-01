// PolicyControl (design system: PolicyControl): the amount threshold per currency, the handoff mode and
// the tool by state matrix. Presentational: the guardrails machine owns the draft and the rules.
//
// Two deviations from the component's README, both because of what the admin API provides:
//   * no "Semilla" (the .env seed): `GET /v1/admin/policy-config` does not return it, so the row shows
//     the value in force ("Vigente") and marks an edited row;
//   * the API needs a threshold greater than zero (the README says "non-negative").

import type { AmountMode, VerificationState } from "@pattern-blue/contracts";
import { Switch } from "@ark-ui/react/switch";
import type { CSSProperties } from "react";
import { FSM_ORDER } from "../machines/policy-draft";
import type { Refusal } from "../machines/guardrails";
import { useI18n } from "./context";
import { money, parseMajor } from "./format";
import { Alert, Icon, STATE_GLYPH } from "./ui";

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
        <div className="pb-thr__seed">
          <span>
            {t("guardrails.thresholds.current")} <b>{savedMinor === undefined ? t("common.empty") : money(savedMinor, currency)}</b>
          </span>
          {edited ? (
            <span className="pb-chip" data-tone="info">
              <Icon name="info" />
              {t("guardrails.thresholds.edited")}
            </span>
          ) : (
            <span>{t("guardrails.thresholds.unchanged")}</span>
          )}
        </div>
        {showDemo && (
          <div className="pb-thr__demo">
            <span>
              {t("guardrails.thresholds.demoCharge", { amount: money(DEMO_CHARGE_MINOR, "USD"), threshold: thresholdText })} →{" "}
              <span className="pb-chip" data-tone={above ? "warning" : "success"}>
                <Icon name={above ? "warning" : "check"} />
                {t(above ? "guardrails.thresholds.above" : "guardrails.thresholds.below")}
              </span>
            </span>
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
            <span>{t("guardrails.thresholds.scale")}</span>
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
          <button key={value} type="button" className="pb-btn pb-btn--sm" role="radio" aria-checked={mode === value} data-mode={value} onClick={() => onChange(value)}>
            {t(value === "flag" ? "guardrails.mode.flagLabel" : "guardrails.mode.blockLabel")} <span className="bo-raw">({value})</span>
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

export function ToolRow({
  tool,
  floor,
  enabled,
  onCell,
  onMaster,
}: {
  tool: string;
  /** The states the code permits, in FSM order. Configuration can only restrict within it. */
  floor: readonly VerificationState[];
  /** The states the draft enables. */
  enabled: readonly VerificationState[];
  onCell: (state: VerificationState) => void;
  onMaster: () => void;
}) {
  const { t, note } = useI18n();
  const nameId = `tool-${tool.replaceAll(".", "-")}`;
  const on = enabled.length > 0;
  const allStates = floor.length === FSM_ORDER.length;
  const toolNote = note(tool);

  return (
    <div className="pb-tool" data-floor={floor.join(", ")}>
      <div className="pb-tool__head">
        <div>
          <span className="pb-tool__name" id={nameId}>
            {tool}
          </span>
          <p className="pb-tool__meta">
            {t("guardrails.tools.floor")}: <b>{allStates ? t("guardrails.tools.allStates") : floor.join(", ")}</b> · {t("guardrails.tools.activeIn")}:{" "}
            <b>{enabled.length === 0 ? t("common.none") : enabled.length === floor.length && allStates ? t("common.all") : enabled.join(", ")}</b>
          </p>
        </div>
        <div className="pb-tool__ctl">
          <span>{on ? t("guardrails.tools.on") : t("guardrails.tools.off")}</span>
          <Switch.Root checked={on} onCheckedChange={onMaster}>
            <Switch.Control className="pb-switch">
              <Switch.Thumb className="pb-switch__thumb" />
            </Switch.Control>
            <Switch.HiddenInput aria-labelledby={nameId} />
          </Switch.Root>
        </div>
      </div>
      {toolNote && <p className="pb-tool__note">{toolNote}</p>}
      <div className="pb-cells" role="group" aria-label={t("guardrails.tools.group", { tool })}>
        {FSM_ORDER.map((state) => {
          const inFloor = floor.includes(state);
          return (
            <button
              key={state}
              type="button"
              className="pb-btn pb-btn--sm pb-btn--secondary"
              role="switch"
              aria-checked={enabled.includes(state)}
              aria-disabled={inFloor ? undefined : true}
              aria-label={inFloor ? undefined : t("guardrails.tools.outsideFloor", { state })}
              data-fsm={state}
              onClick={() => onCell(state)}
            >
              <Icon name={inFloor ? (STATE_GLYPH[state] ?? "minus") : "x"} />
              {state}
            </button>
          );
        })}
      </div>
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
        hint={t("guardrails.tools.refusalHint", { floor: refusal.floor.join(", ") })}
        action={dismiss}
      >
        {t("guardrails.tools.refusalText", { tool: refusal.tool, state: refusal.state })}
      </Alert>
    );
  }
  return (
    <Alert id="refusal" tone="caution" stripe eyebrow={t("guardrails.tools.refusalEyebrow")} hint={refusal.messages.join(" ")} action={dismiss}>
      {t("guardrails.tools.refusalApi")}
    </Alert>
  );
}

