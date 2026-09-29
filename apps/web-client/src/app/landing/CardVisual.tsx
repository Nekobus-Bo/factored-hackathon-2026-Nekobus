import { useI18n } from "../actors";
import { Icon } from "../ui/Icon";

/**
 * A Pattern Blue card mockup, BLOCKED. Decorative art: every value on the plate is masked and fixed
 * for the demo (the design system forbids a real number, holder or expiry).
 */
export function CardVisual() {
  const { dict } = useI18n();
  return (
    <div className="pb-cardvis" data-state="blocked" aria-hidden="true">
      <i className="pb-hexfield" aria-hidden="true" />
      <div className="pb-cardvis__top">
        <span className="pb-cardvis__brand">Pattern Blue</span>
        <span className="pb-chip" data-state="blocked">
          <Icon name="card-blocked" />
          {dict.card.blocked}
        </span>
      </div>
      <div className="pb-cardvis__mid">
        <span className="pb-cardvis__chip" />
        <span className="pb-cardvis__pan">
          <span>••••</span>
          <b>4821</b>
        </span>
      </div>
      <div className="pb-cardvis__bottom">
        <div>
          <span className="pb-cardvis__label">{dict.card.holder}</span>D*** M***
        </div>
        <div>
          <span className="pb-cardvis__label">{dict.card.expires}</span>••/••
        </div>
        <Icon name="hex" />
      </div>
    </div>
  );
}
