#!/bin/sh
# Stop hook: notify an external URL when the agent reaches a terminal state.
#
# This is the human-readable / locally-testable source of truth. The SAME
# script is embedded inline in ../hooks/hooks.json (as the "command" string),
# because that inline copy is what actually runs: when hooks execute as part of
# a plugin, the working directory is the agent's workspace (not this plugin
# directory) and there is no plugin-root path variable, so a relative path to
# this file would not resolve. If you edit this file, re-embed it (see README).
#
# Contract:
#   - stdin  : the HookEvent JSON (drained but not parsed; POSIX sh has no jq).
#   - env    : OPENHANDS_SESSION_ID, OPENHANDS_PROJECT_DIR (set by the runner);
#              OH_CALLBACK_URL / OH_CALLBACK_TOKEN / OH_CALLBACK_PAYLOAD (yours,
#              supplied as conversation secrets — never hard-coded here).
#   - exit 0 : always. This hook only NOTIFIES; it never blocks the agent from
#              finishing. (Exit 2 would block; we deliberately don't.)

# Drain stdin so the writer never sees a broken pipe.
cat >/dev/null 2>&1

# Where to POST. If unset, this plugin is a harmless no-op.
url="${OH_CALLBACK_URL:-}"
if [ -z "$url" ]; then
  exit 0
fi

# Optional shared secret, echoed in a header the receiver can verify.
token="${OH_CALLBACK_TOKEN:-}"

# Optional caller-supplied payload file. When present, its raw contents become
# the POST body ("attach the payload's contents to the request"). Otherwise we
# send a small JSON envelope describing the finish. No customer-identifying
# information is baked into this script — it all comes from your env/secrets.
payload_file="${OH_CALLBACK_PAYLOAD:-}"

tmp="$(mktemp 2>/dev/null || echo "/tmp/oh_finish_cb.$$")"

if [ -n "$payload_file" ] && [ -f "$payload_file" ]; then
  body_file="$payload_file"
else
  sid="${OPENHANDS_SESSION_ID:-}"
  ts="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo "")"
  printf '{"status":"finished","session_id":"%s","finished_at":"%s"}' \
    "$sid" "$ts" >"$tmp"
  body_file="$tmp"
fi

# Fire the callback. Best-effort: short timeout, failures are swallowed so a
# down receiver never stalls or breaks the agent. Your polling loop remains the
# reliability net.
if command -v curl >/dev/null 2>&1; then
  if [ -n "$token" ]; then
    curl -s -m 10 -X POST "$url" \
      -H "Content-Type: application/json" \
      -H "X-Callback-Token: $token" \
      --data-binary @"$body_file" >/dev/null 2>&1 || true
  else
    curl -s -m 10 -X POST "$url" \
      -H "Content-Type: application/json" \
      --data-binary @"$body_file" >/dev/null 2>&1 || true
  fi
fi

rm -f "$tmp" 2>/dev/null || true
exit 0
