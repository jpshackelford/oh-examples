---
description: Automatically configures GPG commit signing at the start of every conversation using a SessionStart hook
triggers:
  - gpg signing
  - sign commits
  - commit signing
  - signed commit
---

# GPG Signer Skill

This skill works automatically through a **SessionStart hook** — you don't need
to invoke it directly.

## What It Does

At the beginning of every conversation, the `gpg-signer` plugin:

1. Reads an ASCII-armored private key from a **custom secret** (default name
   `gpg_key`).
2. Imports it into the sandbox's GnuPG keyring (non-interactively).
3. Configures git **globally** to sign commits and tags with that key:
   - `user.signingkey` = the imported key's fingerprint
   - `commit.gpgsign` = `true`
   - `tag.gpgsign` = `true`
4. Optionally sets `user.name` / `user.email` from the `git_user_name` and
   `git_user_email` secrets, when present.

Because the configuration is **global**, it applies to any repository cloned
later in the conversation — including repos the agent clones on its own.

## Why a SessionStart Hook (not `setup.sh`)

`.openhands/setup.sh` only runs when a conversation is started **with a
repository selected**. Conversations that begin without a repo — or that clone
repos later — never run it, so commit signing is silently missing.

A `SessionStart` hook runs at the beginning of **every** conversation,
regardless of whether a repo was selected, which is exactly when you want
signing configured.

## Required Secret

| Secret name | Contents | Required |
|-------------|----------|----------|
| `gpg_key` | ASCII-armored **private** key (`gpg --armor --export-secret-keys …`) | Yes |
| `git_user_name` | Git author name | Optional |
| `git_user_email` | Git author email (should match a key UID) | Optional |

Add these under **Settings → Secrets** in OpenHands (or pass them per
conversation). If `gpg_key` is missing, the hook logs a note and exits cleanly
without changing anything.

> The secret names are configurable via the `GPG_KEY_SECRET_NAME`,
> `GIT_USER_NAME_SECRET_NAME`, and `GIT_USER_EMAIL_SECRET_NAME` environment
> variables if your organization uses different names.

## How to Verify

Ask me to run:

```bash
git config --global --get commit.gpgsign     # -> true
git config --global --get user.signingkey    # -> your key fingerprint
```

Or make a commit and inspect it:

```bash
git log --show-signature -1
```

A correctly configured session shows `Good signature from "…"`.

## Technical Details

- **Hook type:** `SessionStart` (runs once when the conversation begins)
- **Blocking:** No — `SessionStart` hooks cannot block; the conversation always
  starts. On any failure the hook logs the reason and exits `0`.
- **Logs:** `/tmp/openhands_gpg_setup.log`
- **Non-interactive GnuPG:** enables loopback pinentry so import/signing never
  waits on a TTY prompt.

This is a **setup/automation** hook, not a security gate — it prepares the
environment rather than allowing or denying agent actions.
