import "./styles.css";
import { createRoot } from "react-dom/client";
import { createActor } from "xstate";
import { createApi } from "../api/client";
import { appMachine, browserStorage } from "../machines/app";
import { App } from "./App";

// The BFF answers 401 when the session cookie is missing, tampered with or expired: any such answer sends
// the agent back to the login, wherever the request came from.
const api = createApi(undefined, { onUnauthorized: () => actor.send({ type: "SESSION.EXPIRED" }) });
const actor = createActor(appMachine, { input: { api, storage: browserStorage(), root: document.documentElement } }).start();

const container = document.getElementById("root");
if (!container) throw new Error("index.html has no #root");
createRoot(container).render(<App actor={actor} api={api} />);
