import { useState } from "react";
import { useI18n } from "../actors";
import { Icon } from "../ui/Icon";
import { LangSwitch, MarketSwitch, ThemeSwitch } from "./Switches";
import { Wordmark } from "./Wordmark";

export function Navbar() {
  const { dict } = useI18n();
  const [open, setOpen] = useState(false);
  const t = dict.nav;
  const links = [
    { href: "#productos", label: t.products },
    { href: "#tarjeta-perdida", label: t.lostCard },
    { href: "#s2", label: t.s2 },
    { href: "#ayuda", label: t.help },
  ];
  return (
    <header className="pb-nav" data-open={open ? "true" : "false"}>
      <div className="pb-nav__bar">
        <a className="pb-nav__brand" href="#top" aria-label={t.brandLabel}>
          <Wordmark />
        </a>
        <button
          className="pb-nav__menu"
          type="button"
          aria-expanded={open}
          aria-controls="menu-main"
          onClick={() => setOpen((value) => !value)}
        >
          <Icon name={open ? "x" : "menu"} />
          {t.menu}
        </button>
        <div className="pb-nav__collapse" id="menu-main">
          <nav className="pb-nav__links" aria-label={t.linksLabel}>
            {links.map((link) => (
              <a key={link.href} className="pb-nav__link" href={link.href} onClick={() => setOpen(false)}>
                {link.label}
              </a>
            ))}
          </nav>
          <div className="pb-nav__tools">
            <LangSwitch />
            <MarketSwitch />
            <ThemeSwitch />
          </div>
        </div>
      </div>
    </header>
  );
}
