// Detective mode's card on the Guardrails screen (ADR-0019): one switch for every customer conversation.

import { useMachine } from "@xstate/react";
import { detectiveMachine } from "../machines/detective";
import { useAppServices, useI18n } from "./context";
import { Alert } from "./ui";

export function DetectiveControl() {
  const { t } = useI18n();
  const { api } = useAppServices();
  const [snapshot, send] = useMachine(detectiveMachine, { input: { api } });
  const { state, error } = snapshot.context;
  const saving = snapshot.matches("saving");
  const offered = state?.available === true;
  const enabled = state?.enabled === true;

  return (
    <section className="pb-card pb-policy" aria-labelledby="detective-title" data-detective-control>
      <div className="pb-policy__sec bo-bar">
        <div>
          <h2 className="h2" id="detective-title">
            {t("guardrails.detective.title")}
          </h2>
          <p className="bo-help">{t("guardrails.detective.body")}</p>
        </div>
        {state && (
          <button
            type="button"
            role="switch"
            aria-checked={enabled}
            className={`pb-btn pb-btn--sm ${enabled ? "pb-btn--secondary" : "pb-btn--primary"}`}
            disabled={!offered || saving}
            onClick={() => send({ type: "TOGGLE" })}
          >
            {saving ? t("guardrails.detective.saving") : enabled ? t("guardrails.detective.turnOff") : t("guardrails.detective.turnOn")}
          </button>
        )}
      </div>
      <div className="pb-policy__sec">
        {snapshot.matches("loading") && (
          <p className="pb-t-small" role="status">
            {t("common.loading")}
          </p>
        )}
        {state && (
          <p className="pb-t-small" role="status">
            {offered ? (enabled ? t("guardrails.detective.on") : t("guardrails.detective.off")) : t("guardrails.detective.unavailable")}
          </p>
        )}
        {snapshot.matches("failed") && (
          <Alert
            tone="caution"
            eyebrow={t("guardrails.detective.title")}
            action={
              <button type="button" className="pb-btn pb-btn--secondary pb-btn--sm" onClick={() => send({ type: "RETRY" })}>
                {t("common.retry")}
              </button>
            }
          >
            {error === "unavailable" ? t("errors.unavailable") : t("guardrails.detective.loadFailed")}
          </Alert>
        )}
        {snapshot.matches("ready") && error !== null && (
          <Alert tone="caution" eyebrow={t("guardrails.detective.title")}>
            {error === "unavailable" ? t("errors.unavailable") : t("guardrails.detective.failed")}
          </Alert>
        )}
      </div>
    </section>
  );
}
