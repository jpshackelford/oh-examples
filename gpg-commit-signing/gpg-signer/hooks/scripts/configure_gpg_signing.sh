#!/bin/sh
# SessionStart hook — configure GPG commit signing for the whole conversation.
#
# This is a READABLE REFERENCE COPY of the script that is INLINED into
# ../hooks.json. When the bundle is loaded as a plugin the hook runner executes
# with the working directory set to the agent's workspace (not the plugin
# directory) and there is no plugin-root path variable, so a relative path to
# this file would not resolve — that is why the real logic lives inline in
# hooks.json. Keep the two copies in sync; edit this file first, then mirror it.
#
# Why SessionStart (and not .openhands/setup.sh)? setup.sh only runs when a
# conversation is started with a repository selected. A SessionStart hook runs
# at the beginning of EVERY conversation, so `git commit -S` is configured up
# front and applies to any repo the agent clones later in the session.
#
# Secrets: on the agent-server the hook runs with the same environment that
# setup.sh sees, so a custom secret named `gpg_key` (and, optionally,
# `git_user_name` / `git_user_email`) added in OpenHands is available here as an
# environment variable. Nothing is printed to stdout on success: when a hook
# exits 0 the SDK parses stdout as JSON, so all human-readable output goes to a
# log file instead.

# Fail on unset variables and on unhandled errors (POSIX; no `pipefail`).
set -eu

LOG_FILE="${LOG_FILE:-/tmp/openhands_gpg_setup.log}"
# `exec >>file` is POSIX; avoid bash-only `>(tee ...)` because the runner
# invokes this through `/bin/sh -c`.
exec >>"$LOG_FILE" 2>&1

log() { echo "[gpg-signer] $*"; }

log "SessionStart hook running ($(date -u '+%Y-%m-%dT%H:%M:%SZ'))"

# The secret holding the ASCII-armored private key. Default name is `gpg_key`
# to match the customer's existing setup.sh; override with GPG_KEY_SECRET_NAME.
key_var="${GPG_KEY_SECRET_NAME:-gpg_key}"
# Indirect expansion that works in plain POSIX sh (no bash ${!var}).
key_material="$(eval "printf '%s' \"\${$key_var:-}\"")"

if [ -z "$key_material" ]; then
  log "No GPG key found in \$$key_var — skipping signing setup. (Add a '$key_var' secret to enable it.)"
  exit 0
fi

# Non-interactive GnuPG: no passphrase prompt / TTY in a sandbox.
export GPG_TTY="${GPG_TTY:-$(tty 2>/dev/null || echo /dev/null)}"
GNUPGHOME="${GNUPGHOME:-$HOME/.gnupg}"
export GNUPGHOME
mkdir -p "$GNUPGHOME"
chmod 700 "$GNUPGHOME" 2>/dev/null || true
if ! grep -qs '^allow-loopback-pinentry' "$GNUPGHOME/gpg-agent.conf" 2>/dev/null; then
  echo "allow-loopback-pinentry" >> "$GNUPGHOME/gpg-agent.conf"
fi
if ! grep -qs '^pinentry-mode loopback' "$GNUPGHOME/gpg.conf" 2>/dev/null; then
  echo "pinentry-mode loopback" >> "$GNUPGHOME/gpg.conf"
fi

log "Importing GPG key from \$$key_var ..."
if printf '%s' "$key_material" | gpg --batch --import; then
  log "GPG key imported successfully."
else
  log "GPG import failed. See $LOG_FILE"
  # SessionStart hooks cannot block; exit 0 so the conversation still starts.
  # The agent simply won't have signing configured — the log explains why.
  exit 0
fi

log "Extracting signing key ID ..."
# The first fingerprint (fpr) line is the primary key's fingerprint, which git
# accepts as user.signingkey.
KEY_ID="$(printf '%s' "$key_material" \
  | gpg --show-keys --with-colons 2>/dev/null \
  | awk -F: '/^fpr/{print $10; exit}')"

if [ -z "$KEY_ID" ]; then
  log "Could not determine key ID from the imported key — skipping git config."
  exit 0
fi
log "Key ID: $KEY_ID"

log "Configuring git signing (global, applies to every repo this session) ..."
git config --global user.signingkey "$KEY_ID"
git config --global commit.gpgsign true
git config --global tag.gpgsign true
git config --global gpg.program "$(command -v gpg)"

# Optional identity secrets. Only set them when provided so we never clobber an
# identity that setup.sh or the platform already configured.
name_var="${GIT_USER_NAME_SECRET_NAME:-git_user_name}"
email_var="${GIT_USER_EMAIL_SECRET_NAME:-git_user_email}"
git_user_name="$(eval "printf '%s' \"\${$name_var:-}\"")"
git_user_email="$(eval "printf '%s' \"\${$email_var:-}\"")"
if [ -n "$git_user_name" ]; then
  git config --global user.name "$git_user_name"
fi
if [ -n "$git_user_email" ]; then
  git config --global user.email "$git_user_email"
fi
if [ -n "$git_user_name" ] || [ -n "$git_user_email" ]; then
  log "Git identity: ${git_user_name:-<unchanged>} <${git_user_email:-<unchanged>}>"
fi

log "Done. Commits in this conversation will be GPG-signed."
exit 0
