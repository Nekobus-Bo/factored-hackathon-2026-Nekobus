// @pattern-blue/contracts: the Zod schemas the front ends and their BFFs share.
//
//   common               timestamps, opaque references, error bodies, header names
//   enums                enums that mirror the Python contracts (drift-tested against the JSON Schemas)
//   blocks               message blocks and parseBlocks
//   trace                the detective-mode turn trace (drift-tested against the JSON Schemas)
//   route                the route table helpers
//   orchestrator-chat    the customer chat API
//   orchestrator-agent   the agent API (human takeover)
//   banking-admin        the banking-core admin API
//   bff-client           the web-client BFF routes
//   bff-backoffice       the web-backoffice BFF routes

export * from "./common";
export * from "./enums";
export * from "./blocks";
export * from "./trace";
export * from "./route";
export * from "./orchestrator-chat";
export * from "./orchestrator-agent";
export * from "./banking-admin";
export * from "./bff-client";
export * from "./bff-backoffice";
