// A confirmation dialog on Ark UI's headless Dialog (focus trap, Escape, aria-modal, scroll lock). The
// design system has no dialog, so the card and the buttons are its own (`pb-card`, `pb-btn`), and the
// overlay and centering are layout glue in app.css.

import { Dialog } from "@ark-ui/react/dialog";
import { Portal } from "@ark-ui/react/portal";
import type { ReactNode } from "react";
import { useI18n } from "./context";

export function ConfirmDialog({
  open,
  title,
  description,
  children,
  confirmLabel,
  tone = "primary",
  busy = false,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  title: string;
  description: string;
  children?: ReactNode;
  confirmLabel: string;
  /** `danger` only for an action that overwrites state (the demo reset), and only behind this confirmation. */
  tone?: "primary" | "danger";
  busy?: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const { t } = useI18n();
  return (
    <Dialog.Root open={open} onOpenChange={(details) => !details.open && onCancel()} role="alertdialog" lazyMount unmountOnExit>
      <Portal>
        <Dialog.Backdrop className="bo-backdrop" />
        <Dialog.Positioner className="bo-dialog-positioner">
          <Dialog.Content className="pb-card bo-dialog">
            <Dialog.Title className="h2 bo-dialog__title">{title}</Dialog.Title>
            <Dialog.Description className="bo-dialog__text">{description}</Dialog.Description>
            {children}
            <div className="bo-dialog__actions">
              <button type="button" className="pb-btn pb-btn--ghost pb-btn--sm" onClick={onCancel} disabled={busy}>
                {t("common.cancel")}
              </button>
              <button type="button" className={`pb-btn pb-btn--sm ${tone === "danger" ? "pb-btn--danger" : "pb-btn--primary"}`} onClick={onConfirm} disabled={busy}>
                {confirmLabel}
              </button>
            </div>
          </Dialog.Content>
        </Dialog.Positioner>
      </Portal>
    </Dialog.Root>
  );
}
