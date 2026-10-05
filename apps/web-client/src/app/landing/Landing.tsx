// The home page of Pattern Blue, a fictional bank: Navbar, Hero, its products (FeatureGrid), what to do if you
// lose your card (HowItWorks), S2PromoCard, FaqAccordion and Footer, with the chat dock last. The chat is open on entering and,
// once closed, the hero and the dock open it again, and the hero's button with it open puts the focus in the composer (the navigation bar has no button for it). The whole page follows the global machine's language and theme.

import { useEffect, useState } from "react";
import { ChatDock } from "../chat/ChatDock";
import { useI18n } from "../actors";
import { useSidePanelRoom } from "../hooks";
import { Footer } from "./Footer";
import { Hero } from "./Hero";
import { Navbar } from "./Navbar";
import { FaqAccordion, FeatureGrid, HowItWorks, S2PromoCard } from "./Sections";

/** The page under the chat is inert while the chat is open and takes the whole screen (no room for the demo panel beside it). */
export const pageCovered = (chatOpen: boolean, room: boolean): boolean => chatOpen && !room;

export function Landing({ wide }: { wide?: boolean } = {}) {
  const { dict } = useI18n();
  // Open on entering, also on a phone: the chat is the product. Once closed it stays closed for the visit; a reload opens it again.
  const [chatOpen, setChatOpen] = useState(true);
  // The hero's button: opens the chat if it is closed (the opening focuses the composer) and, raising this counter, asks the open chat for it.
  const [focusRequest, setFocusRequest] = useState(0);
  // With no room for the demo panel the open chat covers the whole screen: the page under it is inert (out of the tab
  // order and of screen readers) until the chat closes or the window has room again. The dock is not part of the page.
  const windowRoom = useSidePanelRoom();
  const room = wide ?? windowRoom;
  const covered = pageCovered(chatOpen, room);

  useEffect(() => {
    document.title = dict.meta.documentTitle;
  }, [dict.meta.documentTitle]);

  return (
    <>
      <Navbar inert={covered} />
      <main inert={covered}>
        <Hero
          onOpenChat={() => {
            setChatOpen(true);
            setFocusRequest((count) => count + 1);
          }}
        />
        <FeatureGrid />
        <HowItWorks />
        <S2PromoCard />
        <FaqAccordion />
      </main>
      <Footer inert={covered} />
      <ChatDock open={chatOpen} onOpenChange={setChatOpen} wide={wide} focusRequest={focusRequest} />
    </>
  );
}
