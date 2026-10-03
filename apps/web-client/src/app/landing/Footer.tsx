import { useI18n } from "../actors";
import { Icon } from "../ui/Icon";

/** The wordmark, the demo note and the small print. The links and the switches live in the sticky navbar. */
export function Footer() {
  const { dict } = useI18n();
  const t = dict.footer;
  return (
    <footer className="pb-footer">
      <div className="pb-footer__inner pb-footer__inner--compact">
        <div className="pb-footer__top">
          <span className="pb-footer__wordmark">Pattern Blue</span>
          <p className="pb-footer__tag">{t.tag}</p>
        </div>
        <p className="pb-footer__demo">
          <Icon name="info" />
          <span>{t.demoNote}</span>
        </p>
        <p className="pb-footer__legal" id="legal">
          {t.legal}
        </p>
      </div>
    </footer>
  );
}
