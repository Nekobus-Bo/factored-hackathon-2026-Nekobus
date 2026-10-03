// Spanish: the reference dictionary. `pt.ts` and `en.ts` must have exactly this shape (the type and
// tests/i18n.test.ts check it). Placeholders are `{name}`; see `format` in ./index.ts.
//
// The landing copy follows packages/design-tokens/reference (Landing, Hero, Navbar, CardVisual,
// FeatureGrid, HowItWorks, S2PromoCard, FaqAccordion, Footer). Its rules hold in every language: a number
// is a product fact (a 6-digit code, 5 minutes of validity, the year of the hackathon), and the demo note
// and the S² small print are always there.

import type { Department, HandoffPriority, HandoffStatus, Locale, ResourceState } from "@pattern-blue/contracts";

const departments = {
  FRAUD_OPERATIONS: "Operaciones de fraude",
  CUSTOMER_SUPPORT: "Atención al cliente",
  DISPUTES: "Disputas",
} as const satisfies Record<Department, string>;

const priorities = {
  URGENT: "Urgente",
  HIGH: "Alta",
  NORMAL: "Normal",
  LOW: "Baja",
} as const satisfies Record<HandoffPriority, string>;

const handoffStatuses = {
  QUEUED: "En la fila",
  ASSIGNED: "Asignado a un agente",
  PENDING: "Pendiente",
} as const satisfies Record<HandoffStatus, string>;

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
    documentTitle: "Pattern Blue · Atención bancaria con IA",
  },
  nav: {
    brandLabel: "Pattern Blue, inicio",
    menu: "Menú",
    linksLabel: "Principal",
    features: "Funciones",
    how: "Cómo funciona",
    s2: "S²",
    help: "Ayuda",
    login: "Ingresar",
    languageLabel: "Idioma",
    marketLabel: "País",
    markets,
    themeLabel: "Tema",
    themeLight: "Tema claro",
    themeDark: "Tema oscuro",
  },
  hero: {
    kicker: "Atención bancaria con IA",
    title: ["Tu tarjeta", "bloqueada", "con comprobante"],
    sub: "El asistente de Pattern Blue verifica tu identidad con un código, bloquea tu tarjeta comprometida y te muestra el comprobante. Si hay una disputa, la pasa a una persona con los hechos ya verificados.",
    ctaPrimary: "Hablar con el asistente",
    ctaSecondary: "Cómo funciona",
    facts: [
      "Código de 6 dígitos, válido 5 minutos.",
      "Comprobante releído de la base de datos.",
      "Español, português y English.",
    ],
    stamp: "Verificado contra la base de datos",
  },
  card: {
    holder: "Titular",
    expires: "Vence",
    blocked: "Bloqueada",
  },
  features: {
    kicker: "Qué hace el asistente",
    title: ["Lo que hace", "el asistente"],
    items: [
      {
        title: "Bloqueo con comprobante",
        text: "Bloqueamos tu tarjeta y te mostramos un comprobante releído de la base de datos. Sin comprobante, no hay confirmación.",
        fact: "Verificado contra la base de datos",
      },
      {
        title: "Identidad con código",
        text: "Antes de actuar te enviamos un código de 6 dígitos. Vale 5 minutos. En la demo el correo es simulado.",
        fact: "6 dígitos · 5 min de validez",
      },
      {
        title: "Disputas con una persona",
        text: "El asistente no resuelve disputas: las pasa a un agente con los hechos ya verificados.",
        fact: "Resolución siempre humana",
      },
      {
        title: "En tu idioma",
        text: "Te atendemos en español, português y English, y puedes cambiar cuando quieras.",
        fact: "ES · PT · EN",
      },
    ],
  },
  flow: {
    kicker: "Paso a paso",
    title: ["Cómo", "funciona"],
    steps: [
      {
        title: "Cuéntale qué pasó",
        text: "Dile al asistente que perdiste la tarjeta o que no reconoces un cargo, y compártele tu número de documento.",
        chip: "Identificado",
      },
      {
        title: "Verifica tu identidad",
        text: "Te enviamos un código de 6 dígitos. Escríbelo en el chat: vale 5 minutos.",
        chip: "Verificado",
      },
      {
        title: "Bloqueamos con comprobante",
        text: "El asistente bloquea la tarjeta y te muestra el comprobante leído de la base de datos.",
        chip: "Tarjeta bloqueada",
      },
      {
        title: "Una persona toma la disputa",
        text: "Si hay un cargo que no reconoces, un agente recibe tu caso con los hechos ya verificados.",
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
    sub: "S² lleva el nombre de un motor de energía infinita: un flujo que nunca se agota.",
    legal: "Activo digital ficticio de demostración. No es una inversión ni un producto real.",
  },
  faq: {
    kicker: "Ayuda",
    title: ["Preguntas", "frecuentes"],
    items: [
      {
        q: "¿Qué pasa si pierdo mi tarjeta?",
        a: "Escríbele al asistente. Verifica tu identidad con un código de 6 dígitos y bloquea la tarjeta. Solo te confirma el bloqueo cuando el comprobante se leyó de la base de datos.",
      },
      {
        q: "¿El asistente puede resolver una disputa?",
        a: "No. Reúne los hechos verificados y pasa el caso a una persona del equipo de Disputas. La resolución es siempre humana.",
      },
      {
        q: "¿Por qué me pide un código?",
        a: "Para comprobar que eres tú antes de bloquear nada. El código tiene 6 dígitos y vale 5 minutos. Pattern Blue nunca te lo pedirá por teléfono ni por correo. En esta demo el correo es simulado y aparece en una bandeja dentro de la página.",
      },
      {
        q: "¿En qué idiomas atiende?",
        a: "En español, português y English. Puedes cambiar de idioma cuando quieras.",
      },
      {
        q: "¿Esto es un banco real?",
        a: "No. Pattern Blue es una demo del Factored AI & Data Hackathon 2026 con datos sintéticos. No hay cuentas, tarjetas ni dinero reales, y S² es un activo ficticio.",
      },
    ],
  },
  footer: {
    tag: "Atención bancaria con IA: nada se da por hecho hasta que se verifica.",
    product: "Producto",
    security: "Seguridad",
    legalGroup: "Legal",
    howWeVerify: "Cómo verificamos",
    faqLink: "Preguntas frecuentes",
    terms: "Términos de la demo",
    privacy: "Privacidad",
    demoNote: "Demo · Factored AI & Data Hackathon 2026 · datos sintéticos",
    legal:
      "Pattern Blue es un proyecto de demostración. No es un banco ni una entidad financiera, y no hay cuentas, tarjetas ni dinero reales. S² es un activo ficticio de demostración. © 2026 Pattern Blue (demo).",
  },
  chat: {
    launcher: "Abrir chat con el asistente",
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
    notSent: "No enviado",
    retry: "Reintentar",
    takeoverStatus: "Un agente está atendiendo tu caso",
    codeExpired: "El código venció",
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
      eyebrow: "Servicio no disponible",
      text: "El asistente no está disponible en este momento. Tu mensaje no se procesó.",
    },
    rateLimited: {
      eyebrow: "Demasiadas solicitudes",
      text: "Recibimos demasiadas solicitudes desde esta red. Intenta de nuevo en {wait}.",
      lessThanMinute: "menos de un minuto",
      minutesOne: "{n} minuto",
      minutesOther: "{n} minutos",
    },
    gone: {
      eyebrow: "Conversación no disponible",
      text: "Esta conversación ya no está disponible. Tu mensaje no se envió.",
      action: "Empezar de nuevo",
    },
    receipt: {
      kicker: "Comprobante",
      aria: "Comprobante de {action}",
      titleCardBlock: "Bloqueé tu tarjeta",
      titleOtpSend: "Te envié un código",
      titleOtpVerify: "Identidad verificada",
      titleOther: "Acción confirmada",
      card: "Tarjeta",
      destination: "Destino",
      reference: "Referencia",
      changedTo: "cambió a",
      foot: "Verificado contra la base de datos",
    },
    states: resourceStates,
    handoff: {
      kicker: "Traspaso",
      aria: "Traspaso a un agente",
      title: "Te pasé con un agente de {department}",
      reference: "Referencia",
      status: "Estado",
      position: "Posición",
      positionValue: "{n} en la fila",
      priority: "Prioridad",
      knowsTitle: "El agente ya sabe",
      knows: ["Lo que ya se verificó en esta conversación.", "Las acciones que ya se realizaron."],
      foot: "Desde aquí el asistente deja de actuar",
      departments,
      priorities,
      statuses: handoffStatuses,
    },
    inbox: {
      noticeTitle: "Te llegó un correo con el código",
      expiresIn: "vence en",
      open: "Abrir bandeja",
      close: "Cerrar bandeja",
      panelTitle: "Bandeja simulada",
      demoTag: "DEMO",
      from: "De",
      fromValue: "Pattern Blue Seguridad",
      to: "Para",
      subject: "Asunto",
      subjectValue: "Tu código de verificación",
      instruction: "Escribe este código en el chat para verificar tu identidad.",
      codeAria: "Código: {digits}",
      codeHiddenAria: "Código oculto",
      reveal: "Mostrar código",
      hide: "Ocultar código",
      expiryLabel: "Vence en",
      note: "Entrega simulada para la demo: no se envió ningún correo real. En producción el código llega al canal registrado del cliente.",
      security: "Pattern Blue nunca te pedirá este código por teléfono ni por correo.",
    },
  },
} as const;
