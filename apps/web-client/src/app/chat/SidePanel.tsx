// The demo panel at the left of the chat: one panel with two tabs, the demo guide and detective mode (the
// detective tab exists only where the environment offers the mode; with no tab to choose, the panel is the guide
// alone). Props only, so it renders on the server in the tests. The chat and its composer stay in sight and usable
// beside it. Below 920px the stylesheet hides it: there the detective view takes the chat's place instead.

import { useRef, type KeyboardEvent, type ReactNode } from "react";
import type { Dictionary } from "../../i18n";
import { Icon } from "../ui/Icon";
import type { SideTab } from "./detective-view";

export const SIDE_PANEL_ID = "side-panel";
const tabId = (tab: SideTab) => `side-tab-${tab}`;

export interface SidePanelProps {
  dict: Dictionary;
  /** Not shown: closed, or the chat is. */
  hidden: boolean;
  /** The tab that shows. */
  tab: SideTab;
  /** The environment offers detective mode: there are two tabs. */
  detectiveOffered: boolean;
  onTab: (tab: SideTab) => void;
  /** Escape inside the panel. */
  onClose?: () => void;
  /** The content of the tab that shows. */
  children: ReactNode;
}

export function SidePanel({ dict, hidden, tab, detectiveOffered, onTab, onClose, children }: SidePanelProps) {
  const tabs = useRef<Partial<Record<SideTab, HTMLButtonElement | null>>>({});
  const order: readonly SideTab[] = ["script", "detective"];

  const onKeyDown = (event: KeyboardEvent) => {
    if (event.key === "Escape" && onClose) {
      event.stopPropagation();
      onClose();
    }
  };
  // Arrows, Home and End move between the two tabs, as on any tab list.
  const onTabKey = (event: KeyboardEvent) => {
    const next = event.key === "ArrowRight" || event.key === "ArrowLeft" ? order[order.indexOf(tab) === 0 ? 1 : 0] : event.key === "Home" ? "script" : event.key === "End" ? "detective" : null;
    if (!next) return;
    event.preventDefault();
    onTab(next);
    tabs.current[next]?.focus();
  };

  return (
    <aside
      className="pb-cut pb-side pb-dock__side"
      id={SIDE_PANEL_ID}
      {...(detectiveOffered ? { "aria-label": dict.chat.side.label } : { "aria-labelledby": "side-title" })}
      hidden={hidden}
      onKeyDown={onKeyDown}
    >
      <header className="pb-side__head">
        {detectiveOffered ? (
          <div className="pb-tabs" role="tablist" aria-label={dict.chat.side.label}>
            {order.map((name) => (
              <button
                key={name}
                ref={(element) => {
                  tabs.current[name] = element;
                }}
                type="button"
                className="pb-tab"
                role="tab"
                id={tabId(name)}
                aria-selected={tab === name}
                aria-controls={`${SIDE_PANEL_ID}-content`}
                tabIndex={tab === name ? 0 : -1}
                data-side-tab={name}
                onClick={() => onTab(name)}
                onKeyDown={onTabKey}
              >
                {name === "script" ? dict.chat.guide.tab : dict.chat.detective.tab}
              </button>
            ))}
          </div>
        ) : (
          <span className="pb-chat__title" id="side-title">
            <Icon name="menu" /> {dict.chat.guide.title}
          </span>
        )}
        {tab === "script" && <span className="pb-tag">{dict.chat.guide.demoTag}</span>}
      </header>
      <div
        className="pb-side__content"
        id={`${SIDE_PANEL_ID}-content`}
        {...(detectiveOffered ? { role: "tabpanel", "aria-labelledby": tabId(tab) } : {})}
      >
        {children}
      </div>
    </aside>
  );
}
