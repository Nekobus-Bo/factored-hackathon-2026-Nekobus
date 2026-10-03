import { useSelector } from "@xstate/react";
import { AppServicesProvider, I18nProvider, useAppServices, useI18n, useLang, type AppActor } from "./context";
import type { Api } from "../api/client";
import { FlowsScreen } from "./FlowsScreen";
import { GuardrailsScreen } from "./GuardrailsScreen";
import { HandoffScreen } from "./HandoffScreen";
import { LoginScreen } from "./LoginScreen";
import { MetricsScreen } from "./MetricsScreen";
import { QueueScreen } from "./QueueScreen";
import { useRoute } from "./router";
import { Shell } from "./Shell";

function Screens() {
  const route = useRoute();
  switch (route.name) {
    // `key` gives each case its own machine: opening another case starts from scratch.
    case "handoff":
      return <HandoffScreen key={route.ref} handoffRef={route.ref} />;
    case "guardrails":
      return <GuardrailsScreen />;
    case "metrics":
      return <MetricsScreen />;
    case "flows":
      return <FlowsScreen />;
    case "queue":
      return <QueueScreen />;
  }
}

function Root() {
  const { t } = useI18n();
  const { actor } = useAppServices();
  const route = useRoute();
  const state = useSelector(actor, (snapshot) => snapshot.value);
  const loginError = useSelector(actor, (snapshot) => snapshot.context.loginError);

  if (state === "booting") {
    return (
      <Shell route={route} authenticated={false}>
        <p className="pb-t-small bo-screen" role="status">
          {t("common.loading")}
        </p>
      </Shell>
    );
  }

  if (state === "authenticated") {
    return (
      <Shell route={route} authenticated>
        <Screens />
      </Shell>
    );
  }

  return (
    <Shell route={route} authenticated={false}>
      <LoginScreen
        submitting={state === "signingIn"}
        error={loginError}
        onSubmit={(email, password) => actor.send({ type: "LOGIN", email, password })}
      />
    </Shell>
  );
}

export function App({ actor, api }: { actor: AppActor; api: Api }) {
  return (
    <AppServicesProvider actor={actor} api={api}>
      <Localized />
    </AppServicesProvider>
  );
}

function Localized() {
  const lang = useLang();
  return (
    <I18nProvider lang={lang}>
      <Root />
    </I18nProvider>
  );
}
