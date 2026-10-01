import { useI18n } from "../actors";
import { Icon } from "../ui/Icon";
import { LangSwitch, ThemeSwitch } from "./Switches";

export function Footer() {
  const { dict } = useI18n();
  const t = dict.footer;
  return (
    <footer className="pb-footer">
      <div className="pb-footer__inner">
        <div className="pb-footer__brand">
          <span className="pb-footer__wordmark">Pattern Blue</span>
          <p className="pb-footer__tag">{t.tag}</p>
        </div>
        <div className="pb-footer__cols">
          <nav className="pb-footer__group" aria-label={t.product}>
            <h3>{t.product}</h3>
            <ul>
              <li>
                <a className="pb-footer__link" href="#funciones">
                  {dict.nav.features}
                </a>
              </li>
              <li>
                <a className="pb-footer__link" href="#como-funciona">
                  {dict.nav.how}
                </a>
              </li>
              <li>
                <a className="pb-footer__link" href="#s2">
                  {dict.nav.s2}
                </a>
              </li>
              <li>
                <a className="pb-footer__link" href="#ayuda">
                  {dict.nav.help}
                </a>
              </li>
            </ul>
          </nav>
          <nav className="pb-footer__group" aria-label={t.security}>
            <h3>{t.security}</h3>
            <ul>
              <li>
                <a className="pb-footer__link" href="#como-funciona">
                  {t.howWeVerify}
                </a>
              </li>
              <li>
                <a className="pb-footer__link" href="#ayuda">
                  {t.faqLink}
                </a>
              </li>
            </ul>
          </nav>
          <nav className="pb-footer__group" aria-label={t.legalGroup}>
            <h3>{t.legalGroup}</h3>
            {/* Placeholders in the demo: there are no legal pages, the links go to the small print. */}
            <ul>
              <li>
                <a className="pb-footer__link" href="#legal">
                  {t.terms}
                </a>
              </li>
              <li>
                <a className="pb-footer__link" href="#legal">
                  {t.privacy}
                </a>
              </li>
            </ul>
          </nav>
        </div>
        <p className="pb-footer__demo">
          <Icon name="info" />
          <span>{t.demoNote}</span>
        </p>
        <div className="pb-footer__bottom">
          <p className="pb-footer__legal" id="legal">
            {t.legal}
          </p>
          <div className="pb-footer__controls">
            <LangSwitch />
            <ThemeSwitch />
          </div>
        </div>
      </div>
    </footer>
  );
}
