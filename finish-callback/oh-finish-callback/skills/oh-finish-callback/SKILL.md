---
description: Notifies an external URL when the agent reaches a terminal state, using a Stop hook
triggers:
  - finish callback
  - terminal state notification
  - stop hook
---

# Finish Callback Skill

This skill works automatically through a **Stop hook** — you don't need to
invoke it directly. It does not change what the agent does; it only sends a
notification once the agent has finished.

## What It Does

When the agent reaches a terminal state (the conversation goes to `FINISHED`),
the Stop hook fires and sends an HTTP `POST` to a URL you control. This lets an
external system (like a Windmill flow) react the instant the run finishes
instead of discovering it by polling.

## How It Works

1. The agent finishes its work and tries to stop.
2. The Stop hook runs **before** the stop is finalized.
3. The hook reads its configuration from environment variables (supplied as
   conversation secrets) and `POST`s to your callback URL.
4. The hook always exits `0`, so it **never blocks** the agent from finishing —
   it only notifies.

## Configuration (conversation secrets)

No URLs or tokens are hard-coded in this plugin. Everything comes from
conversation secrets, injected as environment variables:

| Variable | Required | Meaning |
|----------|----------|---------|
| `OH_CALLBACK_URL` | Yes | Where to `POST`. If unset, the hook is a no-op. |
| `OH_CALLBACK_TOKEN` | No | Sent as the `X-Callback-Token` header so the receiver can verify the caller. |
| `OH_CALLBACK_PAYLOAD` | No | Path to a JSON file whose raw contents become the POST body. If unset, a small default envelope is sent. |

## Request Body

Without `OH_CALLBACK_PAYLOAD`, the hook sends a compact JSON envelope:

```json
{"status": "finished", "session_id": "<session>", "finished_at": "<UTC ISO-8601>"}
```

With `OH_CALLBACK_PAYLOAD` set to a file path, the file's contents are sent
verbatim instead.

## Reliability

The callback is **best-effort**: it uses a short timeout and swallows errors so
a slow or unreachable receiver never stalls or breaks the agent. If the sandbox
dies, the run errors out before `FINISHED`, or the receiver is down, the
callback simply won't arrive. Keep your existing polling loop as the
reliability net; treat the callback as a fast-path that cuts average latency.

## Technical Details

- **Hook Type:** Stop (runs when the agent tries to finish)
- **Matcher:** `*` (not tool-specific)
- **Mode:** `async` (fire-and-forget, so finishing is never delayed)
- **Exit Codes:** `0` = allow finish (always). This hook never returns `2`.
- **Timeout:** 15 seconds
