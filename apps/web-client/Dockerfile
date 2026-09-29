# web-client: the landing, the chat dock and their same-origin BFF. Build context: the repository root
# (`docker build -f apps/web-client/Dockerfile .`). The image holds the production bundle and the server,
# and nothing else: no sources, no node_modules, no package manager cache.

# 1. Every package.json of the workspace, and the lockfile. `bun install --frozen-lockfile` refuses a
#    lockfile that lists a workspace whose package.json is missing, and the root lockfile lists every app
#    and package of the repository (the back office included), so all the manifests are needed, not only
#    the ones this app imports. Everything else is dropped again, so a change to a source file does not
#    invalidate the install layer below.
FROM oven/bun:1.3 AS manifests
WORKDIR /app
COPY package.json bun.lock ./
COPY apps ./apps
COPY packages ./packages
RUN find apps packages -type f ! -name package.json -delete \
 && find apps packages -type d -empty -delete

# 2. Install and build. Only what the bundle imports is copied in: the TypeScript entry of the contracts,
#    the design tokens, and this app.
FROM oven/bun:1.3 AS build
WORKDIR /app
COPY --from=manifests /app ./
RUN bun install --frozen-lockfile
COPY packages/contracts/ts ./packages/contracts/ts
COPY packages/design-tokens/index.css ./packages/design-tokens/index.css
COPY packages/design-tokens/src ./packages/design-tokens/src
COPY packages/design-tokens/dist ./packages/design-tokens/dist
COPY apps/web-client/tsconfig.json ./apps/web-client/tsconfig.json
COPY apps/web-client/src ./apps/web-client/src
RUN bun run --cwd apps/web-client build

# 3. Run. `dist/` is self-contained (the server and the page bundle, dependencies included) and Bun looks
#    its assets up relative to the working directory, so the server starts from the directory that holds it.
FROM oven/bun:1.3 AS runtime
ENV NODE_ENV=production \
    PORT=5173 \
    ORCHESTRATOR_URL=http://orchestrator:8080
WORKDIR /app
COPY --from=build --chown=bun:bun /app/apps/web-client/dist ./
# `bun` is the non-root user (uid 1000) of the official image.
USER bun
EXPOSE 5173
# The image has no curl. A healthcheck for compose:
#   bun -e "fetch('http://127.0.0.1:' + (process.env.PORT ?? 5173) + '/healthz').then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"
CMD ["bun", "server.js"]
