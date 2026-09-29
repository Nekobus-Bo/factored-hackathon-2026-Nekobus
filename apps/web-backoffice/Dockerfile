# web-backoffice: the back-office bundle and its same-origin BFF, as one Bun server.
#
# Build from the repository root, because the app imports two workspace packages:
#   docker build -f apps/web-backoffice/Dockerfile -t pattern-blue/web-backoffice .
# The build context is cut down by Dockerfile.dockerignore next to this file: only the manifests of the
# JS workspace members, the two packages this app imports and the app itself reach the build. The root
# lockfile lists every workspace of the repository (the customer app included) and `bun install
# --frozen-lockfile` refuses one whose package.json is missing, which is why all the manifests are let in.

# --- Build: install with the lockfile as it is, then bundle the server and the page ------------------------
# Pinned to the platform that runs the build, not the one it targets: the bundle is JavaScript, so a
# linux/arm64 image built on an amd64 runner never has to run Bun under emulation. Only the runtime stage
# below takes the target platform.
FROM --platform=$BUILDPLATFORM oven/bun:1.3 AS build
WORKDIR /repo

# The workspace: the root manifest and bun.lock, then the members. `apps/*` and `packages/*` bring the
# package.json of every JS member (the lockfile lists them all, and a frozen install fails if one is
# missing) plus, by the ignore file, the sources of the three this build needs.
COPY package.json bun.lock ./
COPY packages packages
COPY apps apps
RUN --mount=type=cache,target=/root/.bun/install/cache bun install --frozen-lockfile

RUN bun run --cwd apps/web-backoffice build

# --- Run: only the production bundle and the server, as a non-root user ------------------------------------
FROM oven/bun:1.3 AS runtime
ENV NODE_ENV=production \
    PORT=5174
WORKDIR /app

# `dist/` holds server.js (dependencies bundled in), the page and its assets. Nothing else is copied: no
# sources, no node_modules, no lockfile.
COPY --from=build --chown=bun:bun /repo/apps/web-backoffice/dist/ ./

# The `bun` user comes with the base image (uid 1000).
USER bun
EXPOSE 5174

# Liveness only (`GET /healthz` does not look at the upstreams). Compose declares its own check as well.
HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=5 \
  CMD ["bun", "-e", "fetch(`http://127.0.0.1:${process.env.PORT ?? 5174}/healthz`).then((r) => process.exit(r.ok ? 0 : 1), () => process.exit(1))"]

# The server refuses to start under APP_ENV=production with a development password, secret or token.
# Its paths to the bundle are relative to the working directory, which is why WORKDIR is /app.
CMD ["bun", "server.js"]
