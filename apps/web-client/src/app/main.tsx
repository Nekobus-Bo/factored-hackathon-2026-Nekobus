// Entry point. The styles come only from the design-tokens package (tokens first, then the pb-* components),
// plus a small stylesheet of layout glue. The two machines are created here, once, outside React.

import "@pattern-blue/design-tokens/index.css";
import "./app.css";

import { createRoot } from "react-dom/client";
import { createActor } from "xstate";
import { createApiClient } from "../api/client";
import { createAppMachine, browserEnv } from "../machines/app.machine";
import { chatMachine } from "../machines/chat.machine";
import { ActorsProvider } from "./actors";
import { Landing } from "./landing/Landing";

const app = createActor(createAppMachine(browserEnv())).start();

const chat = createActor(chatMachine, {
  input: {
    deps: {
      api: createApiClient(),
      now: () => Date.now(),
      // Unique per message; a retry repeats it. Letters, digits and `_`, 36 characters.
      newId: () => `msg_${crypto.randomUUID().replaceAll("-", "")}`,
    },
    visible: document.visibilityState === "visible",
  },
}).start();

const container = document.getElementById("root");
if (!container) throw new Error("index.html has no #root");
createRoot(container).render(
  <ActorsProvider actors={{ app, chat }}>
    <Landing />
  </ActorsProvider>,
);
