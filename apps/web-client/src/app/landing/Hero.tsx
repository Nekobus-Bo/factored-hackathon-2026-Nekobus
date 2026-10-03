import { useI18n } from "../actors";
import { Icon } from "../ui/Icon";
import { CardVisual } from "./CardVisual";

export function Hero({ onOpenChat }: { onOpenChat: () => void }) {
  const { dict } = useI18n();
  const t = dict.hero;
  return (
    <section className="pb-hero" aria-labelledby="hero-title" id="top">
      <i className="pb-hexfield" aria-hidden="true" />
      <div className="pb-hero__inner">
        <div className="pb-hero__copy">
          <p className="pb-hero__kicker">
            <Icon name="hex" />
            {t.kicker}
          </p>
          <h1 className="pb-hero__title" id="hero-title">
            <span>{t.title[0]}</span>
            <span className="pb-accent">{t.title[1]}</span>
            <span>{t.title[2]}</span>
          </h1>
          <p className="pb-hero__sub">{t.sub}</p>
          <div className="pb-hero__cta">
            <button className="pb-btn pb-btn--primary" type="button" data-open-chat onClick={onOpenChat}>
              <Icon name="chat" />
              {t.ctaPrimary}
            </button>
            <a className="pb-btn pb-btn--secondary" href="#productos">
              {t.ctaSecondary}
            </a>
          </div>
          <p className="pb-hero__fact">
            <Icon name="check" />
            {t.fact}
          </p>
        </div>
        <div className="pb-hero__visual" aria-hidden="true">
          <span className="pb-hero__slab pb-hero__slab--a" />
          <span className="pb-hero__slab pb-hero__slab--b" />
          <CardVisual state="active" />
        </div>
      </div>
    </section>
  );
}
