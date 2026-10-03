// HandoffCard as the case summary (design system: HandoffCard, as changed by the declutter review of
// 2026-10-02): what the customer asks, the disputed charge, what the bank verified, what the assistant
// did and what the customer answered about it, with the full log of calls on demand. Everything comes
// from what banking-core stored with the handoff. The card never proposes a resolution.

import type { HandoffDetail } from "@pattern-blue/contracts";
import { useState } from "react";
import { AuditLog, ChargeBlock, disputedCharge, FeedbackFact, IdentityFact, PolicyFacts, SaidQuotes, WriteFacts } from "./CaseFacts";
import { useI18n } from "./context";
import { Icon } from "./ui";

export function HandoffCard({ detail, initiallyOpenLog = false }: { detail: HandoffDetail; initiallyOpenLog?: boolean }) {
  const { t } = useI18n();
  const [logOpen, setLogOpen] = useState(initiallyOpenLog);
  const { summary } = detail;
  const charge = disputedCharge(summary);
  const base = `case-${detail.handoff_ref}`;
  const calls = summary.actions_taken.length;

  return (
    <article className="pb-card pb-sum" aria-label={t("handoff.summaryLabel")}>
      <section className="pb-sum__sec" aria-labelledby={`${base}-asks`}>
        <h2 className="pb-sum__h" id={`${base}-asks`}>
          {t("handoff.asks")}
        </h2>
        <SaidQuotes summary={summary} />
      </section>

      {charge && (
        <section className="pb-sum__sec" aria-labelledby={`${base}-charge`}>
          <h2 className="pb-sum__h" id={`${base}-charge`}>
            {t("handoff.charge")}
          </h2>
          <ChargeBlock charge={charge} />
        </section>
      )}

      <section className="pb-sum__sec" aria-labelledby={`${base}-verified`}>
        <h2 className="pb-sum__h" id={`${base}-verified`}>
          {t("handoff.verified")}
        </h2>
        <ul className="pb-facts">
          <IdentityFact summary={summary} />
          <PolicyFacts summary={summary} />
        </ul>
      </section>

      <section className="pb-sum__sec" aria-labelledby={`${base}-did`}>
        <h2 className="pb-sum__h" id={`${base}-did`}>
          {t("handoff.did.title")}
        </h2>
        <ul className="pb-facts">
          <WriteFacts summary={summary} />
          <FeedbackFact feedback={detail.feedback} />
        </ul>
        {calls > 0 && (
          <>
            <button type="button" className="pb-more" aria-expanded={logOpen} aria-controls={`${base}-log`} onClick={() => setLogOpen(!logOpen)}>
              <Icon name="chev1" />
              {t("handoff.log", { count: calls })}
            </button>
            <div id={`${base}-log`} hidden={!logOpen}>
              <AuditLog summary={summary} id={`${base}-calls`} />
            </div>
          </>
        )}
      </section>

      <section className="pb-sum__sec">
        <p className="pb-sum__foot">{t("handoff.footnote")}</p>
      </section>
    </article>
  );
}
