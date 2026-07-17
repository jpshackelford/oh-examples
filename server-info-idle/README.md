# Detect an Idle Agent via `/server_info.idle_time` (the platform's own signal)

Detect when an agent has gone quiet by polling the agent-server's built-in idle
timer: `GET /server_info` reports `idle_time`, the seconds since the last
activity on the server. This is the **exact signal `runtime-api` polls** to
decide when a sandbox is idle enough to pause/reap — this example uses the same
signal for your own "has the workspace gone quiet?" check.

> **Cloud-friendly.** `GET /server_info` is a plain read on the agent-server, so
> the same code works against a **Cloud** sandbox's agent-server URL + session
> key (see [`start-sandbox`](../start-sandbox/)) as well as the local Docker
> server used here.

One file:

- [`idle_poll.py`](./idle_poll.py) — starts a local agent-server in Docker,
  creates + runs a conversation, then polls `/server_info` until `idle_time`
  crosses a threshold and declares the agent idle.

## APIs used

### 1. Agent Server — started locally in Docker

- Image: `ghcr.io/openhands/agent-server:latest-python` (listens on **8000**
  inside the container).
- Auth header: `X-Session-API-Key: <session key>` (seeded via the
  `SESSION_API_KEY` env var; on Cloud it is the sandbox's `session_api_key`).
- Endpoints:
  - `GET  /health` — server readiness
  - `GET  /server_info` — the idle timer (see below)
  - `POST /api/conversations` — create + auto-run a conversation

### 2. `GET /server_info`

Returns a `ServerInfo` object. The fields this example reads:

| Field | Meaning |
|-------|---------|
| `idle_time` | Seconds since the last activity (file ops, agent steps, ACP heartbeat). Drops while the agent works, climbs once it stops. |
| `uptime` | Seconds since the server started. |
| `runtime_idle_timeout_seconds` | The platform's own reap threshold — how long `runtime-api` lets a sandbox sit idle before pausing/stopping it (typically 1200–1800s). **Only populated on the managed platform; it is `null` on a plain local agent-server like the one this demo starts.** |

On the managed platform, `runtime-api` reaps a sandbox roughly when
`idle_time >= runtime_idle_timeout_seconds`. Locally that field is `null` (there
is no reaper), so this demo ignores it and instead uses its own much smaller
threshold (`--idle-threshold`, default 15s) so you can watch idle detection fire
quickly against the same `idle_time` signal.

## `idle_time` vs. `execution_status`

They answer different questions — pick per your need:

| | `idle_time` (this example) | `execution_status` |
|---|---|---|
| **Question** | "Has the *workspace* gone quiet?" | "Is *this conversation* done?" |
| **Granularity** | Server-wide heartbeat | Per-conversation state machine |
| **Distinguishes finished / error / stuck?** | No | Yes (`is_terminal()`) |
| **How to consume** | Poll `GET /server_info` | Push via [WebSocket](../websocket-events/) / [webhook](https://github.com/jpshackelford/oh-examples/pull/22) |
| **Used by the platform for** | Reaping idle sandboxes | Reporting run completion |

Use `idle_time` when you just want "nothing is happening anymore" without
subscribing to a conversation; use `execution_status` when you need an
authoritative terminal signal.

## The flow

```
  idle_poll.py                     Docker: agent-server
      |                                   |
      |-- docker run -------------------->|
      |-- GET /health ------------------->|
      |<-- ok -----------------------------|
      |-- GET /server_info (baseline) --->|  idle_time, runtime_idle_timeout_seconds
      |-- POST /api/conversations (run:true) -->|
      |                          agent runs (idle_time stays low)
      |-- GET /server_info (loop) ------->|  idle_time climbing...
      |   ...until idle_time > threshold -> "agent idle"
      |-- docker rm -f (teardown) -------->|
```

## Run it

Docker must be running.

```bash
pip install requests

export LLM_API_KEY=...                     # required
export LLM_MODEL=litellm_proxy/...         # required
export LLM_BASE_URL=https://...            # optional (provider default if unset)

python idle_poll.py
```

`idle_poll.py` flags / env vars:

| Flag | Env var | Default |
|------|---------|---------|
| `--llm-api-key` | `LLM_API_KEY` | — (required) |
| `--llm-model` | `LLM_MODEL` | — (required) |
| `--llm-base-url` | `LLM_BASE_URL` | none |
| `--session-key` | `SESSION_API_KEY` | `local-demo-key` |
| `--image` | `OH_AGENT_SERVER_IMAGE` | `ghcr.io/openhands/agent-server:latest-python` |
| `--server-port` | `OH_SERVER_PORT` | `8000` |
| `--idle-threshold` | — | `15` (seconds) |
| `--poll-interval` | — | `3` (seconds) |
| `--watch-timeout` | — | `180` |
| `--keep` | — | off (container removed at end) |

## What it prints

```
container: 049e77ec611b
health: ok
baseline /server_info: idle_time=1.0s runtime_idle_timeout_seconds=None
conversation: b9c0b61d-a924-47c1-ae1b-a79035967925

polling /server_info.idle_time every 3.0s; declaring idle at > 15.0s

  idle_time=  0.0s  uptime=1.0s
  idle_time=  3.0s  uptime=4.0s
  idle_time=  6.0s  uptime=7.0s     # climbing while nothing runs yet
  idle_time=  9.0s  uptime=10.0s
  idle_time= 12.0s  uptime=13.0s
  idle_time=  1.0s  uptime=16.0s    # drops when the agent acts
  idle_time=  4.0s  uptime=19.0s
  idle_time=  7.0s  uptime=22.0s
  idle_time= 10.0s  uptime=25.0s
  idle_time= 13.0s  uptime=28.0s
  idle_time= 16.0s  uptime=31.0s    # climbs again after the agent stops

agent idle: idle_time exceeded 15.0s — the workspace has gone quiet.
(this is the same signal runtime-api uses to reap sandboxes; for a
per-conversation terminal state use execution_status)
removed container oh-idle-demo
```

## Notes

- **Coarse by design.** `idle_time` cannot tell you *why* things went quiet
  (finished vs. errored vs. stuck vs. simply waiting). It is a heartbeat, not a
  state machine. That is exactly why the platform uses it for reaping and not for
  reporting completion.
- **Threshold choice.** Set `--idle-threshold` well above your longest expected
  gap between agent actions (LLM latency, long tool calls), or you will declare
  "idle" mid-run. The platform's default (`runtime_idle_timeout_seconds`) is
  deliberately large for this reason.
- **Cloud:** call `GET <agent-server-url>/server_info` with the sandbox's
  `session_api_key`. No webhook injection or socket needed — it is a plain read.
- Full agent-server schema: `http://localhost:<server-port>/openapi.json`.

## Related

- [`websocket-events`](../websocket-events/) — authoritative per-conversation
  terminal state over the WebSocket (push)
- [`react-to-state-websocket`](../react-to-state-websocket/) — react to *every*
  `execution_status` transition over the WebSocket, on the Cloud substrate
- [`react-to-state-webhooks`](https://github.com/jpshackelford/oh-examples/pull/22)
  (proposed) — state changes pushed from the server via `WebhookSpec`
  (local-only)
- [`start-sandbox`](../start-sandbox/) — how to reach a Cloud sandbox's
  agent-server URL + session key
