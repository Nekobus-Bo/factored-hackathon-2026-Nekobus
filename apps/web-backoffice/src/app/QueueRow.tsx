// QueueRow (design system: QueueRow): one row of the handoff queue. The design's `lang` and masked
// `customer` columns have no source in the admin API (`HandoffItem` carries neither), so they give way to
// what the API does have: the status with its queue position, and the agent who holds the case. The
// priority and the department are shown in words and, beside them, as the raw enum.

import type { HandoffItem } from "@pattern-blue/contracts";
import { useI18n } from "./context";
import { waitText } from "./format";
import { HandoffStatusChip, PriorityChip } from "./ui";

export function QueueRow({ item, now }: { item: HandoffItem; now: number }) {
  const { t } = useI18n();
  const status = [t(`enums.status.${item.status}`), item.queue_position !== null ? t("queue.position", { position: item.queue_position }) : null]
    .filter((part) => part !== null)
    .join(" · ");

  return (
    <div className="pb-qrow" role="row">
      <span role="cell" data-col="id">
        <a className="pb-caseid" href={`#/handoffs/${item.handoff_ref}`} aria-label={t("queue.openCase", { ref: item.handoff_ref })}>
          {item.handoff_ref}
        </a>
      </span>
      <span role="cell" data-col="pri">
        <span className="bo-cell">
          <PriorityChip priority={item.priority} />
          <span className="pb-t-small">{t(`enums.priority.${item.priority}`)}</span>
        </span>
      </span>
      <span role="cell" data-col="dept">
        <span className="bo-cell">
          <span className="pb-t-small">{t(`enums.department.${item.department}`)}</span>
          <span>{item.department}</span>
        </span>
      </span>
      <span role="cell" data-col="status">
        <span className="bo-cell">
          <HandoffStatusChip status={item.status} />
          <span className="pb-t-small">{status}</span>
        </span>
      </span>
      <span role="cell" data-col="wait">
        {waitText(Date.parse(item.created_at), now)}
      </span>
      <span role="cell" data-col="agent">
        {item.assigned_agent ?? <span className="pb-t-small">{t("queue.unassigned")}</span>}
      </span>
    </div>
  );
}

export function QueueTable({ items, now }: { items: readonly HandoffItem[]; now: number }) {
  const { t } = useI18n();
  return (
    <div className="pb-queue bo-queue" role="table" aria-label={t("queue.tableLabel")}>
      <div className="pb-queue__head" role="row">
        <span role="columnheader">{t("queue.col.case")}</span>
        <span role="columnheader">{t("queue.col.priority")}</span>
        <span role="columnheader">{t("queue.col.department")}</span>
        <span role="columnheader">{t("queue.col.status")}</span>
        <span role="columnheader">{t("queue.col.wait")}</span>
        <span role="columnheader">{t("queue.col.agent")}</span>
      </div>
      {items.map((item) => (
        <QueueRow key={item.handoff_ref} item={item} now={now} />
      ))}
    </div>
  );
}
