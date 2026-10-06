#!/usr/bin/env bash
# Runs capture-ui.tsx. This folder is outside the Bun workspace, so it has no node_modules of its own:
# link the web client's react, react-dom and xstate in here first. They have to be the very same copies
# the components use, or React sees two of itself and every hook throws.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
app="$here/../../apps/web-client/node_modules"
if [ ! -d "$app/react" ]; then
  echo "apps/web-client has no node_modules: run 'bun install' in apps/web-client first" >&2
  exit 1
fi
mkdir -p "$here/node_modules"
for pkg in react react-dom xstate; do
  [ -e "$here/node_modules/$pkg" ] || ln -s "$app/$pkg" "$here/node_modules/$pkg"
done
cd "$here/../.."
TZ=UTC exec bun demo/pitch/capture-ui.tsx "$@"
