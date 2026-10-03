import { useState } from "react";
import { useI18n } from "../actors";
import { Icon } from "../ui/Icon";
import { LangSwitch, ThemeToggle } from "./Switches";

export function Navbar({ onOpenChat }: { onOpenChat: () => void }) {
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
            <ThemeToggle />
            {/* The chat is the one thing in the demo that works: it stays one click away while the page scrolls. */}
            <button
              className="pb-btn pb-btn--secondary"
              type="button"
              data-open-chat
              onClick={() => {
                setOpen(false);
                onOpenChat();
              }}
            >
              <Icon name="chat" />
              {t.openChat}
            </button>
          </div>
        </div>
      </div>
    </header>
  );
}
