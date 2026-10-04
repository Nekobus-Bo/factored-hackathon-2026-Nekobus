// Spanish: the reference dictionary. `pt.ts` and `en.ts` must have exactly this shape (the type and
// tests/i18n.test.ts check it). Placeholders are `{name}`; see `format` in ./index.ts.
//
// The landing is the home page of a fictional bank: its products, what to do if you lose your card, and
// answers. Its rules hold in every language: a number is a product fact (a 6-digit code, 5 minutes of
// validity, the year of the hackathon), the products are the ones the demo data has (a checking account and a
// debit card), and the demo note and the S² small print are always there. The copy is plain: no colon as a
// connector, the actor named, one idea per sentence (packages/design-tokens/README.md lists the changes).

import type { Department, Locale, ResourceState } from "@pattern-blue/contracts";

const departments = {
  FRAUD_OPERATIONS: "Operaciones de fraude",
  CUSTOMER_SUPPORT: "Atención al cliente",
  DISPUTES: "Disputas",
} as const satisfies Record<Department, string>;

/** State chips inside the chat speak the customer's language, never the raw enum. */
const resourceStates = {
  NONE: "Sin estado",
  ACTIVE: "Activa",
  BLOCKED: "Bloqueada",
  FROZEN: "Congelada",
  ISSUED: "Emitida",
  PENDING: "Pendiente",
  VERIFIED: "Verificado",
  EXPIRED: "Vencido",
  LOCKED: "Bloqueado",
  QUEUED: "En la fila",
  ASSIGNED: "Asignado",
  RESOLVED: "Resuelto",
  ANONYMOUS: "Sin identificar",
  IDENTIFIED: "Identificado",
  OTP_PENDING: "Código pendiente",
  HANDED_OFF: "Con un agente",
} as const satisfies Record<ResourceState, string>;

/** The markets, by the country's name: the market switch reads them aloud (it shows only the code). */
const markets = {
  "es-CO": "Colombia",
  "es-MX": "México",
  "es-AR": "Argentina",
  "pt-BR": "Brasil",
  "en-US": "Estados Unidos",
} as const satisfies Record<Locale, string>;

export const es = {
  meta: {
    documentTitle: "Pattern Blue · Banco digital",
  },
  nav: {
    brandLabel: "Pattern Blue, inicio",
    menu: "Menú",
    linksLabel: "Principal",
    products: "Productos",
    lostCard: "Tarjeta perdida",
    s2: "S²",
    help: "Ayuda",
    openChat: "Abrir chat",
    languageLabel: "Idioma",
    marketLabel: "País",
    markets,
    themeToDark: "Cambiar a tema oscuro",
    themeToLight: "Cambiar a tema claro",
  },
  hero: {
    kicker: "Banco digital",
    title: ["Tu banco", "responde", "en el chat"],
    sub: "Pattern Blue tiene cuenta corriente y tarjeta débito. Si pierdes la tarjeta, el asistente la bloquea en el chat. Si ves un cargo que no hiciste, una persona del equipo revisa tu caso.",
    ctaPrimary: "Hablar con el asistente",
    ctaSecondary: "Ver productos",
    fact: "Atención en español, português y English",
  },
  card: {
    holder: "Titular",
    expires: "Vence",
    active: "Activa",
    blocked: "Bloqueada",
  },
  products: {
    title: "Productos",
    items: [
      {
        title: "Cuenta corriente",
        text: "La cuenta donde está tu dinero. Cada compra que haces con la tarjeta sale de aquí.",
      },
      {
        title: "Tarjeta débito",
        text: "Pagas en comercios con el saldo de tu cuenta. Si la pierdes, la bloqueas desde el chat.",
      },
      {
        title: "Ayuda en el chat",
        text: "Escríbele al asistente para bloquear la tarjeta o reportar un cargo. Una persona revisa cada disputa.",
      },
    ],
  },
  flow: {
    title: "Si pierdes tu tarjeta",
    steps: [
      {
        title: "Escribe en el chat",
        text: "Cuéntale al asistente qué pasó y dale tu número de documento.",
        chip: "Identificado",
      },
      {
        title: "Confirma que eres tú",
        text: "Te enviamos un código de 6 dígitos a tu correo. Escríbelo en el chat antes de 5 minutos.",
        chip: "Verificado",
      },
      {
        title: "Bloqueamos la tarjeta",
        text: "El asistente la bloquea y te muestra el comprobante.",
        chip: "Tarjeta bloqueada",
      },
      {
        title: "Revisamos el cargo",
        text: "Si hay un cargo que no hiciste, una persona del equipo de Disputas lo revisa.",
        chip: "Con un agente",
      },
    ],
  },
  s2: {
    label: "S²",
    top: "Pattern Blue · Cripto",
    demo: "Solo demo",
    ticker: "S2",
    title: ["Liquidez", "sin límite"],
    sub: "S² es la criptomoneda ficticia de Pattern Blue. No tiene precio y no se puede comprar.",
    legal: "Activo digital ficticio de demostración. No es una inversión ni un producto real.",
  },
  faq: {
    title: "Preguntas frecuentes",
    items: [
      {
        q: "¿Qué hago si pierdo mi tarjeta?",
        a: "Escribe en el chat. El asistente confirma que eres tú con un código y bloquea la tarjeta. Cuando el banco registra el bloqueo, te muestra el comprobante.",
      },
      {
        q: "Veo un cargo que no hice. ¿Qué pasa ahora?",
        a: "Cuéntaselo al asistente. Él pasa tu caso a una persona del equipo de Disputas, que lo revisa y te escribe en el mismo chat.",
      },
      {
        q: "¿Por qué me piden un código?",
        a: "Para confirmar que eres tú antes de bloquear la tarjeta. El código tiene 6 dígitos y vale 5 minutos. Nunca te lo pediremos por teléfono ni por correo. En esta demo el correo es simulado y lo ves en una bandeja dentro de la página.",
      },
      {
        q: "¿En qué idiomas me atienden?",
        a: "En español, português y English. Puedes cambiar de idioma cuando quieras.",
      },
      {
        q: "¿Pattern Blue es un banco real?",
        a: "No. Es una demo del Factored AI & Data Hackathon 2026 con datos sintéticos. No hay cuentas, tarjetas ni dinero reales.",
      },
    ],
  },
  footer: {
    tag: "Un banco digital ficticio, hecho para esta demo.",
    demoNote: "Demo · Factored AI & Data Hackathon 2026 · datos sintéticos",
    legal:
      "Pattern Blue es un proyecto de demostración. No es un banco ni una entidad financiera, y no hay cuentas, tarjetas ni dinero reales. S² es un activo ficticio de demostración. © 2026 Pattern Blue (demo).",
  },
  chat: {
    launcher: "Abrir chat con el asistente",
    launcherLabel: "Asistente",
    panel: "Chat con el asistente",
    title: "Asistente",
    close: "Cerrar chat",
    log: "Mensajes",
    composerLabel: "Mensaje",
    placeholder: "Escribe tu mensaje",
    send: "Enviar mensaje",
    greeting: "Hola, soy el asistente de Pattern Blue. ¿En qué te ayudo?",
    typing: "El asistente está escribiendo",
    roles: {
      assistant: "Asistente",
      customer: "Tú",
      agent: "Agente humano",
    },
    codePrefix: "Código",
    notSent: "No pudimos enviar tu mensaje.",
    retry: "Reintentar",
    takeoverStatus: "Un agente está atendiendo tu caso",
    codeExpired: "El código venció",
    detective: {
      toggle: "Modo detective",
      back: "Volver al chat",
      views: "Vista",
      steps: "Pasos",
      timeline: "Tiempo",
      turns: "Turnos",
      turn: "Turno {n}",
      empty: "Sin turnos todavía.",
      open: "Ver este turno en el modo detective",
      kinds: {
        encoder: "Encoder",
        masking: "Enmascarado",
        decisions: "Decisiones",
        canned_reply: "Respuesta fija",
        llm_call: "LLM",
        tool_call: "Herramienta",
        engine_handoff: "Derivación",
        blocks: "Respuesta",
        takeover: "Agente",
      },
      status: { ok: "ok", refused: "rechazado", error: "error", skipped: "omitido" },
      detail: {
        unavailable: "no disponible",
        regexOnly: "solo regex: encoder no disponible",
        maskFailed: "enmascarado fallido: no se envió nada",
        tools: "Herramientas ({n})",
        result: "Resultado",
        engine: "motor",
        fallback: "respaldo",
      },
    },
    chip: {
      anonymous: "Sin identificar",
      identified: "Identificado",
      otpPending: "Código pendiente",
      verified: "Verificado",
      locked: "Sesión bloqueada",
      handedOff: "Con un agente",
      active: "Tarjeta activa",
      blocked: "Tarjeta bloqueada",
    },
    unavailable: {
      text: "El asistente no está disponible.",
    },
    rateLimited: {
      text: "Demasiadas solicitudes desde esta red. Intenta de nuevo en {wait}.",
      lessThanMinute: "menos de un minuto",
      minutesOne: "{n} minuto",
      minutesOther: "{n} minutos",
    },
    gone: {
      text: "Esta conversación ya no está disponible. Tu mensaje no se envió.",
      action: "Empezar de nuevo",
    },
    receipt: {
      titleCardBlock: "Bloqueé tu tarjeta {target}",
      titleCardAlreadyBlocked: "Tu tarjeta {target} ya estaba bloqueada",
      titleOtpSend: "Te envié un código a {target}",
      titleOtpVerify: "Identidad verificada",
      titleOther: "Acción confirmada",
      reference: "Comprobante",
      changedTo: "cambió a",
      unchanged: "Sin cambios",
      verified: "Verificado contra la base de datos · {time}",
    },
    states: resourceStates,
    handoff: {
      title: "Te pasé con un agente de {department}",
      caseLabel: "Caso",
      note: "La persona que tome tu caso ve lo que verificamos y lo que hicimos. Desde aquí el asistente deja de actuar.",
      departments,
    },
    inbox: {
      expiresIn: "Vence en",
      open: "Abrir bandeja",
      noticeFallback: "Te enviamos un código a {destination}.",
      panelTitle: "Bandeja simulada",
      close: "Cerrar bandeja",
      demoTag: "DEMO",
      fromValue: "Pattern Blue Seguridad",
      subjectValue: "Tu código de verificación",
      codeAria: "Código: {digits}",
      codeHiddenAria: "Código oculto",
      reveal: "Mostrar código",
      hide: "Ocultar código",
      note: "Entrega simulada. No enviamos ningún correo real. Pattern Blue nunca te pedirá este código por teléfono ni por correo.",
    },
    feedback: {
      question: "¿Te ayudó el asistente?",
      yes: "Sí",
      no: "No",
      yesLabel: "Sí, el asistente me ayudó",
      noLabel: "No, el asistente no me ayudó",
      thanks: "Gracias por tu respuesta.",
      failed: "No pudimos guardar tu respuesta.",
    },
  },
} as const;
