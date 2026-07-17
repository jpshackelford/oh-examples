# React to State Changes via Webhooks (local agent-server, no polling)

React to OpenHands conversation state changes with **outbound webhooks** from
the agent-server — event-driven, no polling. The agent-server POSTs to a small
HTTP receiver whenever a conversation starts/pauses/resumes/stops, and streams
batched events alongside.

> **⚠️ LOCAL-ONLY — this does not work on OpenHands Cloud.**
> Cloud sandboxes run with `deferred_init=False`, so `POST /api/init` returns
> **404** and there is no way to inject a `WebhookSpec` into a running sandbox.
> Webhooks can therefore only be registered on an agent-server **you start
> yourself** (via the startup config file or `OH_*` env vars). To react to
> conversation state on Cloud, consume the **WebSocket** instead — see
> [oh-websocket-example](https://github.com/jpshackelford/oh-websocket-example).
>
> For a Cloud sandbox you drive over REST (still polling-based), see
> [`start-sandbox`](../start-sandbox/).

Two files:

- [`receiver.py`](./receiver.py) — a stdlib-only HTTP server (no deps) that
  accepts the two webhook callbacks and prints one concise line each.
- [`run_demo.py`](./run_demo.py) — orchestrates the whole demo: starts a local
  agent-server in Docker configured to call the receiver, creates + runs a
  conversation, and tears the container down.

## APIs used

### 1. Agent Server — started locally in Docker

- Image: `ghcr.io/openhands/agent-server:latest-python`, the binary target
  built from the
  [software-agent-sdk Dockerfile](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-agent-server/openhands/agent_server/docker/Dockerfile).
  Its entrypoint is `python -m openhands.agent_server`, listening on port
  **8000** inside the container.
- Auth header: `X-Session-API-Key: <session key>` — the first entry of
  `session_api_keys` in the startup config. The same key is echoed back to your
  receiver on every callback, so the receiver can authenticate the server.
- Endpoints this example uses:
  - `GET  /health` — readiness check (server state, **not** conversation state)
  - `POST /api/conversations` — create a conversation; required body field is
    `workspace` (e.g. `{"kind":"LocalWorkspace","working_dir":"/workspace/project"}`)
    plus an `agent` carrying an `llm`, and an optional `initial_message`
  - `POST /api/conversations/{id}/run` — start the agent loop (a conversation
    created with a runnable `initial_message` auto-starts, so this may return
    **409 "already running"** — that is expected and benign)

### 2. Webhook config — how the server learns where to call

Supplied via the **startup config** JSON at
`workspace/openhands_agent_server_config.json` (override with
`OPENHANDS_AGENT_SERVER_CONFIG_PATH`), which `run_demo.py` mounts into the
container. The relevant slice:

```json
{
  "session_api_keys": ["local-demo-key"],
  "webhooks": [
    {
      "base_url": "http://host.docker.internal:8080",
      "event_buffer_size": 1,
      "flush_delay": 1.0
    }
  ]
}
```

`WebhookSpec` fields: `base_url` (required), `headers`, `event_buffer_size`
(default 5), `flush_delay` (default 30.0s), `num_retries` (default 3),
`retry_delay` (default 5), `max_queue_size` (default 1000). This demo sets
`event_buffer_size=1` and `flush_delay=1.0` so events are forwarded almost
immediately instead of batched.

### 3. The two derived callback URLs

From a single `base_url`, the agent-server POSTs to:

- `{base_url}/conversations` — the full `ConversationInfo`, fired on conversation
  **START / PAUSE / RESUME / STOP**. This is the "state changed" signal; read
  `id` and `execution_status` from it.
- `{base_url}/events/{conversation_id_hex}` — a JSON array of batched `Event`
  objects (`ActionEvent`, `ObservationEvent`, `MessageEvent`,
  `ConversationStateUpdateEvent`, `SystemPromptEvent`, …).

`execution_status` is one of: `idle`, `running`, `paused`,
`waiting_for_confirmation`, `finished`, `error`, `stuck`, `deleting`.

## The flow

```
  run_demo.py                      Docker: agent-server            receiver.py
      |                                   |                            |
      |-- write config (webhook -> host)  |                            |
      |-- docker run (mount config) ----->|                            |
      |-- GET /health (poll SERVER only)  |                            |
      |<-- ok -----------------------------|                            |
      |-- POST /api/conversations -------->|                            |
      |-- POST /{id}/run ----------------->| (auto-running -> 409)      |
      |                                    |                            |
      |                          conversation START ----> POST /conversations
      |                                    |               (execution_status)
      |                          agent runs, emits events -> POST /events/{id}
      |                                    |               (batched)
      |   *** no polling of conversation state anywhere ***             |
      |                                    |                            |
      |-- docker rm -f (teardown) -------->|                            |
```

## Run it

Docker must be running. The container reaches your host via
`host.docker.internal` (Docker Desktop provides it; on Linux `run_demo.py`
adds `--add-host host.docker.internal:host-gateway`).

```bash
pip install requests

export LLM_API_KEY=...                     # required
export LLM_MODEL=litellm_proxy/...         # required
export LLM_BASE_URL=https://...            # optional (provider default if unset)

# terminal 1 — start the receiver
python receiver.py

# terminal 2 — run the demo (defaults to receiver on port 8080)
python run_demo.py
```

If port 8080 is taken, pick another and tell both sides:

```bash
python receiver.py --port 8791            # terminal 1
RECEIVER_PORT=8791 python run_demo.py     # terminal 2
```

`run_demo.py` flags / env vars:

| Flag | Env var | Default |
|------|---------|---------|
| `--llm-api-key` | `LLM_API_KEY` | — (required) |
| `--llm-model` | `LLM_MODEL` | — (required) |
| `--llm-base-url` | `LLM_BASE_URL` | none |
| `--session-key` | `SESSION_API_KEY` | `local-demo-key` |
| `--image` | `OH_AGENT_SERVER_IMAGE` | `ghcr.io/openhands/agent-server:latest-python` |
| `--server-port` | `OH_SERVER_PORT` | `8000` |
| `--receiver-host` | `RECEIVER_HOST` | `host.docker.internal` |
| `--receiver-port` | `RECEIVER_PORT` | `8080` |
| `--observe-seconds` | — | `20` |
| `--keep` | — | off (container removed at end) |

## What it prints

`run_demo.py` (terminal 2):

```
webhook target (from container): http://host.docker.internal:8791
  -> POST http://host.docker.internal:8791/conversations (state changes)
  -> POST http://host.docker.internal:8791/events/{id} (batched events)
container: 13ee756cf2cd
health: ok
conversation: 603e4620-df37-414d-af42-296dd562bfae
run: 409 (409 = already running, expected)

watching webhooks for 20s (see the receiver terminal for callbacks)...
removed container oh-webhook-demo
```

`receiver.py` (terminal 1) — the actual event-driven signal, no polling:

```
[receiver] listening on http://0.0.0.0:8791 (POST /conversations, POST /events/{id})
[events/603e4620df37414daf42296dd562bfae] 1 event(s): ConversationStateUpdateEvent
[events/603e4620df37414daf42296dd562bfae] 1 event(s): SystemPromptEvent
[events/603e4620df37414daf42296dd562bfae] 1 event(s): ConversationStateUpdateEvent
[conversations] id=603e4620-df37-414d-af42-296dd562bfae execution_status=idle
[events/603e4620df37414daf42296dd562bfae] 1 event(s): MessageEvent
[events/603e4620df37414daf42296dd562bfae] 1 event(s): ConversationStateUpdateEvent
[events/603e4620df37414daf42296dd562bfae] 1 event(s): ActionEvent
[events/603e4620df37414daf42296dd562bfae] 1 event(s): ObservationEvent
[events/603e4620df37414daf42296dd562bfae] 1 event(s): ConversationStateUpdateEvent
```

## Notes

- **Why local-only, in one line:** on Cloud there is no supported path to hand a
  `WebhookSpec` to a running sandbox (`/api/init` → 404), so the server never
  learns your receiver's URL. Locally you own the startup config, so you can.
- **Reachability:** the URL in `base_url` must be reachable **from inside the
  container**. `host.docker.internal` points at your host; alternatively run the
  container with `--network host` (Linux) and use `http://127.0.0.1:<port>`.
- **Auth:** whatever you set as the first `session_api_keys` entry is sent to the
  receiver as `X-Session-API-Key`. Verify it in the receiver if you want to
  reject spoofed calls; this demo just prints.
- **Batching:** with the defaults (`event_buffer_size=5`, `flush_delay=30s`)
  events arrive in larger, less frequent batches. This demo lowers both so the
  output is immediate.
- **No conversation-state polling:** `run_demo.py` polls `GET /health` only to
  learn when the *server* is up. It never reads conversation `execution_status`
  over REST — every state signal comes from the `/conversations` webhook.
- Full agent-server schema: `http://localhost:<server-port>/openapi.json` once
  the container is healthy.
