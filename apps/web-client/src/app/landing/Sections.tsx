// FeatureGrid, HowItWorks, S2PromoCard and FaqAccordion: the sections between the hero and the footer.

import { Accordion } from "@ark-ui/react/accordion";
import { useI18n } from "../actors";
import { Icon, type IconName } from "../ui/Icon";
import { StateChip, type ChipStateName } from "../ui/StateChip";

/** The two-line title card of a section. */
function SectionHead({ id, kicker, kickerIcon, title }: { id: string; kicker: string; kickerIcon: IconName; title: readonly string[] }) {
  return (
    <header className="pb-section__head">
      <p className="pb-section__kicker">
        <Icon name={kickerIcon} />
        {kicker}
      </p>
      <h2 className="pb-section__title" id={id}>
        {title.map((line) => (
          <span key={line}>{line}</span>
        ))}
      </h2>
    </header>
  );
}

// One entry per feature the product has, in the order the design system fixes.
const FEATURE_ICONS: readonly IconName[] = ["card-blocked", "mail", "handoff", "chat"];
const FEATURE_FACT_ICONS: readonly IconName[] = ["shield-check", "clock", "user", "hex"];

export function FeatureGrid() {
  const { dict } = useI18n();
  const t = dict.features;
  return (
    <section className="pb-section" id="funciones" aria-labelledby="feat-title">
      <SectionHead id="feat-title" kicker={t.kicker} kickerIcon="hex" title={t.title} />
      <ul className="pb-features">
        {t.items.map((item, index) => (
          <li className="pb-feature" key={item.title}>
            <span className="pb-feature__icon" aria-hidden="true">
              <Icon name={FEATURE_ICONS[index] ?? "hex"} />
            </span>
            <h3 className="pb-feature__title">{item.title}</h3>
            <p className="pb-feature__text">{item.text}</p>
            <p className="pb-feature__fact">
              <Icon name={FEATURE_FACT_ICONS[index] ?? "hex"} />
              {item.fact}
            </p>
          </li>
        ))}
      </ul>
    </section>
  );
}

const FLOW_CHIPS: ReadonlyArray<{ state: ChipStateName }> = [
  { state: "identified" },
  { state: "verified" },
  { state: "blocked" },
  { state: "handed-off" },
];

export function HowItWorks() {
  const { dict } = useI18n();
  const t = dict.flow;
  return (
    <section className="pb-section" id="como-funciona" aria-labelledby="flow-title">
      <SectionHead id="flow-title" kicker={t.kicker} kickerIcon="chev1" title={t.title} />
      <ol className="pb-flow" role="list">
        {t.steps.map((step, index) => (
          <li className="pb-flow__item" key={step.title}>
            <h3 className="pb-flow__title">{step.title}</h3>
            <p className="pb-flow__text">{step.text}</p>
            <span className="pb-flow__state">
              <StateChip state={FLOW_CHIPS[index]?.state ?? "identified"} label={step.chip} />
            </span>
          </li>
        ))}
      </ol>
    </section>
  );
}

/** S²: a fictional demo asset. No price, chart, link or button, and the tag and the small print stay. */
export function S2PromoCard() {
  const { dict } = useI18n();
  const t = dict.s2;
  return (
    <section className="pb-section" id="s2" aria-label={t.label}>
      <div className="pb-section__narrow">
        <aside className="pb-s2" aria-labelledby="s2-title">
          <i className="pb-hexfield" aria-hidden="true" />
          <div className="pb-s2__top">
            <span>{t.top}</span>
            <span className="pb-s2__demo">{t.demo}</span>
          </div>
          <div className="pb-s2__mark">
            <span className="pb-s2__glyph" aria-hidden="true">
              {t.label}
            </span>
            <span className="pb-s2__ticker">
              <Icon name="infinity" /> {t.ticker}
            </span>
          </div>
          <h2 className="pb-s2__title" id="s2-title">
            {t.title[0]}
            <br />
            {t.title[1]}
          </h2>
          <p className="pb-s2__sub">{t.sub}</p>
          <div className="pb-gauge pb-gauge--sm pb-s2__reactor" aria-hidden="true">
            <div className="pb-gauge__track">
              <div className="pb-gauge__fill" />
            </div>
          </div>
          <p className="pb-s2__legal">{t.legal}</p>
        </aside>
      </div>
    </section>
  );
}

export function FaqAccordion() {
  const { dict } = useI18n();
  const t = dict.faq;
  return (
    <section className="pb-section" id="ayuda" aria-labelledby="faq-title">
      <SectionHead id="faq-title" kicker={t.kicker} kickerIcon="info" title={t.title} />
      {/* Ark UI's accordion: one item open at a time, collapsible, the first open. The design system's CSS reads its data attributes. */}
      <Accordion.Root className="pb-faq" collapsible multiple={false} defaultValue={["faq-0"]}>
        {t.items.map((item, index) => (
          <Accordion.Item key={item.q} value={`faq-${index}`} className="pb-faq__item">
            <h3 className="pb-faq__heading">
              <Accordion.ItemTrigger className="pb-faq__trigger">
                <span>{item.q}</span>
                {/* A span, as in the design system's markup: a div is not allowed inside a button. */}
                <Accordion.ItemIndicator asChild>
                  <span className="pb-faq__indicator" aria-hidden="true">
                    <Icon name="plus" />
                    <Icon name="minus" />
                  </span>
                </Accordion.ItemIndicator>
              </Accordion.ItemTrigger>
            </h3>
            <Accordion.ItemContent className="pb-faq__content">
              <p>{item.a}</p>
            </Accordion.ItemContent>
          </Accordion.Item>
        ))}
      </Accordion.Root>
    </section>
  );
}
