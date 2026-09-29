import { useState } from "react";
import { useI18n } from "../actors";
import { Icon } from "../ui/Icon";
import { LangSwitch, ThemeSwitch } from "./Switches";

export function Navbar() {
  const { dict } = useI18n();
  const [open, setOpen] = useState(false);
  const t = dict.nav;
  const links = [
    { href: "#funciones", label: t.features },
    { href: "#como-funciona", label: t.how },
    { href: "#s2", label: t.s2 },
    { href: "#ayuda", label: t.help },
  ];
  return (
    <header className="pb-nav" data-open={open ? "true" : "false"}>
      <div className="pb-nav__bar">
        <a className="pb-nav__brand" href="#top" aria-label={t.brandLabel}>
          Pattern Blue
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
            <ThemeSwitch />
            {/* Decorative in the demo: there is no account, session or authentication behind it. */}
            <a className="pb-btn pb-btn--secondary" href="#ingresar">
              {t.login}
            </a>
          </div>
        </div>
      </div>
    </header>
  );
}
