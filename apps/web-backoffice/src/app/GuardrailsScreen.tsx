import { useMachine } from "@xstate/react";
import { guardrailsMachine } from "../machines/guardrails";
import { describeChanges, floorOf, invalidThresholds, type Change, policyDirty, toolsDirty } from "../machines/policy-draft";
import { ConfirmDialog } from "./ConfirmDialog";
import { DetectiveControl } from "./DetectiveControl";
import { useAppServices, useI18n } from "./context";
import { money } from "./format";
import { MatrixLegend, ModeGroup, RefusalBanner, ThresholdRow, ToolMatrix } from "./PolicyControl";
import { Alert } from "./ui";

export function GuardrailsScreen() {
  const { t } = useI18n();
  const { api } = useAppServices();
  const [snapshot, send] = useMachine(guardrailsMachine, { input: { api } });
  const { context } = snapshot;

  if (snapshot.matches("loading")) {
    return (
      <section className="bo-screen" aria-labelledby="guardrails-title">
        <h1 className="h1" id="guardrails-title">
          {t("guardrails.title")}
        </h1>
        <p className="pb-t-small" role="status">
          {t("common.loading")}
        </p>
      </section>
    );
  }

  const { policy, tools, draft } = context;
  if (snapshot.matches("failed") || !policy || !tools) {
    return (
      <section className="bo-screen" aria-labelledby="guardrails-title">
        <h1 className="h1" id="guardrails-title">
          {t("guardrails.title")}
        </h1>
        <Alert
          tone="caution"
          eyebrow={t("guardrails.title")}
          action={
            <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => send({ type: "RETRY" })}>
              {t("common.retry")}
            </button>
          }
        >
          {context.loadError === "unavailable" ? t("errors.unavailable") : t("guardrails.loadFailed")}
        </Alert>
      </section>
    );
  }

  const dirty = policyDirty(draft, policy) || toolsDirty(draft, tools);
  const canSave = snapshot.can({ type: "SAVE.REQUEST" });
  const saving = snapshot.matches({ ready: "savingPolicy" }) || snapshot.matches({ ready: "savingTools" });
  const resetting = snapshot.matches({ ready: "resetting" });
  const invalid = invalidThresholds(draft).length > 0;
  const currencies = Object.keys(draft.thresholds);
  const changes = describeChanges(draft, policy, tools);

  const savedText = context.saved
    ? context.saved.policy !== undefined && context.saved.tools !== undefined
      ? t("guardrails.saved", { policy: context.saved.policy, tools: context.saved.tools })
      : context.saved.policy !== undefined
        ? t("guardrails.savedPolicy", { policy: context.saved.policy })
        : t("guardrails.savedTools", { tools: context.saved.tools as number })
    : null;

  return (
    <section className="bo-screen" aria-labelledby="guardrails-title">
      <div className="bo-bar">
        <h1 className="h1" id="guardrails-title">
          {t("guardrails.title")}
        </h1>
        <span className="pb-t-small">{t("guardrails.version", { policy: policy.version, tools: tools.version })}</span>
      </div>

      <div className="bo-notices">
        {savedText && (
          <Alert tone="success" eyebrow={t("guardrails.title")}>
            {savedText}
          </Alert>
        )}
        {context.saveError !== null && context.refusal?.source !== "api" && (
          <Alert tone="caution" eyebrow={t("guardrails.title")} hint={t("guardrails.saveFailed")}>
            {context.saveError === "unavailable" ? t("errors.unavailable") : t("errors.generic")}
          </Alert>
        )}
        {context.resetResult && (
          <Alert tone="success" eyebrow={t("guardrails.reset.done")}>
            {t("guardrails.reset.result", {
              reset: context.resetResult.cards_reset,
              changed: context.resetResult.cards_changed,
              limits: context.resetResult.attempt_limits_cleared,
              tools: context.resetResult.tool_policy_version,
              toolsChanged: context.resetResult.tool_policy_changed ? t("guardrails.reset.toolsChanged") : "",
            })}
          </Alert>
        )}
        {context.resetError !== null && (
          <Alert tone="caution" eyebrow={t("guardrails.reset.title")}>
            {context.resetError === "forbidden" ? t("guardrails.reset.disabled") : context.resetError === "unavailable" ? t("errors.unavailable") : t("guardrails.reset.failed")}
          </Alert>
        )}
      </div>

      <section className="pb-card pb-policy" aria-labelledby="policy-title">
        <div className="pb-policy__sec">
          <h2 className="h2" id="policy-title">
            {t("guardrails.policy.title")}
          </h2>
          <p>{t("guardrails.policy.intro")}</p>
        </div>

        <div className="pb-policy__sec">
          <h3>{t("guardrails.thresholds.title")}</h3>
          <p>{t("guardrails.thresholds.help")}</p>
          {currencies.map((currency) => (
            <ThresholdRow
              key={currency}
              currency={currency}
              value={draft.thresholds[currency] ?? ""}
              savedMinor={policy.thresholds_minor[currency]}
              onChange={(value) => send({ type: "THRESHOLD.SET", currency, value })}
            />
          ))}
        </div>

        <div className="pb-policy__sec">
          <h3>{t("guardrails.mode.title")}</h3>
          <ModeGroup mode={draft.mode} onChange={(mode) => send({ type: "MODE.SET", mode })} />
        </div>

        <div className="pb-policy__sec bo-tools">
          <h3>{t("guardrails.tools.title")}</h3>
          <p>{t("guardrails.tools.intro")}</p>
          <MatrixLegend />
          <ToolMatrix
            tools={Object.keys(tools.code_floor)}
            floorOf={(tool) => floorOf(tools, tool)}
            enabled={(tool) => draft.tools[tool] ?? []}
            onCell={(tool, state) => send({ type: "CELL.TOGGLE", tool, state })}
            onMaster={(tool) => send({ type: "TOOL.TOGGLE", tool })}
          />
          {context.refusal && <RefusalBanner refusal={context.refusal} onDismiss={() => send({ type: "REFUSAL.DISMISS" })} />}
        </div>

        <div className="pb-policy__sec pb-policy__foot">
          <span className="pb-t-small">{dirty ? t("guardrails.foot.dirty") : t("guardrails.foot.audited")}</span>
          <span className="bo-actions">
            <button type="button" className="pb-btn pb-btn--ghost pb-btn--sm" disabled={!dirty || saving} onClick={() => send({ type: "DISCARD" })}>
              {t("guardrails.foot.discard")}
            </button>
            <button type="button" className="pb-btn pb-btn--primary pb-btn--sm" disabled={!canSave || saving || invalid} onClick={() => send({ type: "SAVE.REQUEST" })}>
              {saving ? t("guardrails.foot.saving") : t("guardrails.foot.save")}
            </button>
          </span>
        </div>
      </section>

      <DetectiveControl />

      <section className="pb-card pb-policy" aria-labelledby="reset-title">
        <div className="pb-policy__sec pb-policy__foot">
          <div>
            <h2 className="h2" id="reset-title">
              {t("guardrails.reset.title")}
            </h2>
            <p className="bo-help">{t("guardrails.reset.body")}</p>
          </div>
          <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" disabled={resetting || saving} onClick={() => send({ type: "RESET.REQUEST" })}>
            {resetting ? t("guardrails.reset.running") : t("guardrails.reset.button")}
          </button>
        </div>
      </section>

      <ConfirmDialog
        open={snapshot.matches({ ready: "confirmingSave" })}
        title={t("guardrails.confirmSave.title")}
        description={t("guardrails.confirmSave.body")}
        confirmLabel={t("guardrails.confirmSave.confirm")}
        onConfirm={() => send({ type: "SAVE.CONFIRM" })}
        onCancel={() => send({ type: "SAVE.CANCEL" })}
      >
        <ul className="bo-changes">
          {changes.map((change, index) => (
            <li key={index}>
              <ChangeLine change={change} />
            </li>
          ))}
        </ul>
      </ConfirmDialog>

      <ConfirmDialog
        open={snapshot.matches({ ready: "confirmingReset" })}
        title={t("guardrails.reset.confirmTitle")}
        description={t("guardrails.reset.confirmBody")}
        confirmLabel={t("guardrails.reset.confirm")}
        tone="danger"
        onConfirm={() => send({ type: "RESET.CONFIRM" })}
        onCancel={() => send({ type: "RESET.CANCEL" })}
      />
    </section>
  );
}

function ChangeLine({ change }: { change: Change }) {
  const { t } = useI18n();
  if (change.kind === "mode") {
    const word = (mode: "flag" | "block") => t(mode === "flag" ? "guardrails.mode.flagLabel" : "guardrails.mode.blockLabel");
    return <>{t("guardrails.confirmSave.mode", { from: word(change.from), to: word(change.to) })}</>;
  }
  if (change.kind === "threshold") {
    return (
      <>
        {t("guardrails.confirmSave.threshold", {
          currency: change.currency,
          from: change.from === undefined ? t("common.empty") : money(change.from, change.currency),
          to: money(change.to, change.currency),
        })}
      </>
    );
  }
  const states = (list: readonly string[]) => (list.length === 0 ? t("common.none") : list.join(", "));
  return <>{t("guardrails.confirmSave.tool", { tool: change.tool, from: states(change.from), to: states(change.to) })}</>;
}
