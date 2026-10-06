// Renders the product's real customer page to static HTML, so S04 of the film shows the chat the project
// actually ships instead of a hand-written mock-up. Same components, same stylesheets: `Transcript` and
// `Blocks` are props-only for exactly this reason, and apps/web-client/tests/render.test.tsx renders the
// same tree with `renderToStaticMarkup`.
//
//   TZ=UTC bun demo/pitch/capture-ui.tsx      # from the repository root, so the workspace deps resolve
//
// Writes demo/pitch/ui-chat.html, which render.mjs inlines into film.local.html. Re-run it whenever the
// chat UI changes; `node render.mjs` reads whatever is in that file.
//
// The conversation is the film's: the es-CO compromised card, verified with a code, blocked with a receipt.
// The blocks are the shapes banking-core returns; the words around them come from the product's own
// dictionary, never from here.

import { renderToStaticMarkup } from "react-dom/server";
import { createActor } from "xstate";
import { ActorsProvider } from "../../apps/web-client/src/app/actors";
import { Landing } from "../../apps/web-client/src/app/landing/Landing";
import { StateChip } from "../../apps/web-client/src/app/ui/StateChip";
import { dictionaries } from "../../apps/web-client/src/i18n";
import { createAppMachine, type AppEnv } from "../../apps/web-client/src/machines/app.machine";
import { createWorld, json, START } from "../../apps/web-client/tests/world";

const OUT = new URL("./ui-chat.html", import.meta.url);
/* 02:15 on the night of the film's lock screen. The script runs under TZ=UTC so the bubbles read it back. */
const NIGHT = Date.parse("2026-10-02T02:15:00Z");
const CONVERSATION = "conv_0123456789abcdef0123456789abcdef";

const dict = dictionaries.es;

const TURN_ONE = [
  { type: "text", text: "Puedo bloquear tu tarjeta ahora. Primero confirmo que eres tú: te envié un código de 6 dígitos a d***@example.com." },
  {
    type: "receipt",
    receipt: {
      action: "otp.send",
      target_masked: "d***@example.com",
      state_before: "IDENTIFIED",
      state_after: "OTP_PENDING",
      verified_at: "2026-10-02T02:15:28Z",
      audit_id: "aud_00020479",
    },
  },
];

const TURN_TWO = [
  {
    type: "receipt",
    receipt: {
      action: "otp.verify",
      target_masked: "chal_7f3a91c25a10",
      state_before: "OTP_PENDING",
      state_after: "VERIFIED",
      verified_at: "2026-10-02T02:16:12Z",
      audit_id: "aud_00020480",
    },
  },
  { type: "text", text: "Listo, bloqueé tu tarjeta •••• 4821. Nadie más puede usarla." },
  {
    type: "receipt",
    receipt: {
      action: "card.block",
      target_masked: "**** **** **** 4821",
      state_before: "ACTIVE",
      state_after: "BLOCKED",
      verified_at: "2026-10-02T02:16:40Z",
      audit_id: "aud_00020481",
    },
  },
];

const world = createWorld();
world.advance(NIGHT - START);
world.script("sendMessage", json({ conversation_id: CONVERSATION, blocks: TURN_ONE }), json({ conversation_id: CONVERSATION, blocks: TURN_TWO }));

world.send("me clonaron la tarjeta, yo no hice esa compra", "es", "es-CO");
await world.settle();
world.advance(62_000);
world.send("482916", "es", "es-CO");
await world.settle();

const env: AppEnv = { storage: null, root: null, navigatorLanguage: "es-CO" };
const page = renderToStaticMarkup(
  <ActorsProvider actors={{ app: createActor(createAppMachine(env)).start(), chat: world.actor }}>
    <Landing wide />
  </ActorsProvider>,
);
world.stop();

/* The header chip is one state at a time; the film plays three. Render each with the product's own
   component and put all three in the holder, for film.js to show by time. */
const chip = (state: "otp-pending" | "verified" | "blocked", id: string) =>
  renderToStaticMarkup(<StateChip state={state} label={dict.chat.chip[state === "otp-pending" ? "otpPending" : state]} />).replace(
    "<span ",
    `<span id="${id}" `,
  );
const holder = `<span class="chat-head-chip">${renderToStaticMarkup(<StateChip state="blocked" label={dict.chat.chip.blocked} />)}</span>`;
if (!page.includes(holder)) {
  throw new Error("the chat header no longer ends on the 'Tarjeta bloqueada' chip inside .chat-head-chip: check ChatDock's header before re-rendering the film");
}
const chips = `<span class="chat-head-chip">${[chip("otp-pending", "s04-chip-1"), chip("verified", "s04-chip-2"), chip("blocked", "s04-chip-3")].join("")}</span>`;

/* The typing dots are only in the markup while a turn is in flight; the film plays two of those moments. */
const typing = `<div class="pb-typing" id="s04-typing" role="status"><span class="pb-sr">${dict.chat.typing}</span><i></i><i></i><i></i></div>`;

const html = page
  .replace(holder, chips)
  .replace('<div class="pb-chat__log"', '<div id="s04-log" class="pb-chat__log"')
  .replace(/(<\/div>)(?=<\/div>\s*(?:<form|<div class="pb-chat__composer))/, `${typing}$1`);

for (const [what, mark] of [["the log", 'id="s04-log"'], ["the typing dots", 'id="s04-typing"'], ["the chips", 'id="s04-chip-1"']] as const) {
  if (!html.includes(mark)) throw new Error(`capture-ui could not place ${what}: the chat markup moved, so the film would render without it`);
}

await Bun.write(OUT, `<!-- generated by demo/pitch/capture-ui.tsx: the product's real customer page. Do not edit by hand. -->\n${html}\n`);
console.log(`wrote ui-chat.html (${(html.length / 1024).toFixed(0)} KB)`);
