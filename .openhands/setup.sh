#!/usr/bin/env bash
#
# .openhands/setup.sh — runs automatically every time OpenHands starts working
# with this repository (see https://docs.all-hands.dev/usage/customization/repository).
#
# It is also what the `clone-and-attach` example executes after it shallow-clones
# this repo into a sandbox, so keep it fast and side-effect free.
set -euo pipefail

echo "[oh-examples setup.sh] running in $(pwd)"
echo "[oh-examples setup.sh] python: $(python3 --version 2>&1)"

# Sync dependencies with uv when it is available; harmless to skip otherwise.
if command -v uv >/dev/null 2>&1; then
  echo "[oh-examples setup.sh] uv detected — running 'uv sync'"
  uv sync --frozen 2>/dev/null || uv sync || echo "[oh-examples setup.sh] uv sync skipped"
else
  echo "[oh-examples setup.sh] uv not found — skipping dependency sync"
fi

echo "[oh-examples setup.sh] done"
