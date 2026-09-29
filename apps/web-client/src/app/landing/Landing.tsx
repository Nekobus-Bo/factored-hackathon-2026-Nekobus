// The simulated Pattern Blue fintech: Navbar, Hero, FeatureGrid, HowItWorks, S2PromoCard, FaqAccordion and
// Footer, with the chat dock last. The whole page follows the global machine's language and theme.

import { useEffect, useState } from "react";
import { ChatDock } from "../chat/ChatDock";
import { useI18n } from "../actors";
import { Footer } from "./Footer";
import { Hero } from "./Hero";
import { Navbar } from "./Navbar";
import { FaqAccordion, FeatureGrid, HowItWorks, S2PromoCard } from "./Sections";

export function Landing() {
  const { dict } = useI18n();
  const [chatOpen, setChatOpen] = useState(false);

  useEffect(() => {
    document.title = dict.meta.documentTitle;
  }, [dict.meta.documentTitle]);

  return (
    <>
      <Navbar />
      <main>
        <Hero onOpenChat={() => setChatOpen(true)} />
        <FeatureGrid />
        <HowItWorks />
        <S2PromoCard />
        <FaqAccordion />
      </main>
      <Footer />
      <ChatDock open={chatOpen} onOpenChange={setChatOpen} />
    </>
  );
}
