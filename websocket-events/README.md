# Detect Terminal State over the WebSocket (local agent-server, no polling)

Detect the moment a conversation **finishes** by reading the agent-server's V1
**WebSocket** — event-driven, no polling of conversation state. The agent-server
streams every event (including state changes) over
`/sockets/events/{conversation_id}`; this example connects, watches for a
terminal `execution_status`, announces it, and exits.

> **Push, and Cloud-friendly.** The agent-server `WebhookSpec`
> (see the proposed [`react-to-state-webhooks`](https://github.com/jpshackelford/oh-examples/pull/22) example)
> is *push from the server* and must be configured with your receiver URL —
> impossible on OpenHands Cloud, where you cannot inject webhook config into a
> running sandbox.
> The WebSocket is *pull-connected by the client*, so the exact same client code
> also works against a **Cloud** sandbox's agent-server URL (use `wss://…` and
> the per-sandbox session key from the sandbox-create call — see
> [`start-sandbox`](../start-sandbox/) for how to obtain both). This demo runs
> locally so it is fully reproducible without a Cloud account.

One file:

- [`watch_ws.py`](./watch_ws.py) — starts a local agent-server in Docker,
  creates + runs a conversation, connects the WebSocket, prints each event as it
  arrives, and reports the terminal state.

## APIs used

### 1. Agent Server — started locally in Docker

- Image: `ghcr.io/openhands/agent-server:latest-python`, the binary target built
  from the
  [software-agent-sdk Dockerfile](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-agent-server/openhands/agent_server/docker/Dockerfile).
  It listens on port **8000** inside the container.
- Auth header: `X-Session-API-Key: <session key>`. `watch_ws.py` seeds it with
  the `SESSION_API_KEY` env var, which the server reads into its accepted-key
  list (and secret key). On a Cloud sandbox this is the `session_api_key`
  returned by the sandbox-create call instead.
- Endpoints this example uses:
  - `GET  /health` — readiness check (server state, **not** conversation state)
  - `POST /api/conversations` — create a conversation; body carries a
    `workspace`, an `agent` with an `llm`, and an `initial_message` with
    `run: true` so the agent loop auto-starts

### 2. The WebSocket — `/sockets/events/{conversation_id}`

- `ws://localhost:<port>/sockets/events/{conversation_id}` locally, or
  `wss://…` against a Cloud sandbox agent-server.
- **Auth:** pass `?session_api_key=<key>` as a query parameter (what the SDK's
  own `RemoteConversation` does). A first-message `{"type":"auth", ...}` frame is
  also supported.
- **Replay:** add `?resend_mode=all` to replay events emitted before you
  connected, so a fast run that finishes during startup is not missed.
  (`resend_mode=since&after_timestamp=…` replays from a point in time.)
- Each frame is a serialized `Event`. State changes arrive as
  `ConversationStateUpdateEvent` in one of two shapes:
  - per-field: `{"key": "execution_status", "value": "finished"}`
  - full snapshot: `{"key": "full_state", "value": {..., "execution_status": …}}`

`execution_status` is one of: `idle`, `running`, `paused`,
`waiting_for_confirmation`, `finished`, `error`, `stuck`, `deleting`. The
**terminal** set (what this demo waits for) is `finished`, `error`, `stuck`.
`idle` is intentionally excluded — it is also the *initial* state before a run
starts, so treating it as terminal would fire a false positive.

## The flow

```
  watch_ws.py                      Docker: agent-server
      |                                   |
      |-- docker run -------------------->|
      |-- GET /health (poll SERVER only)  |
      |<-- ok -----------------------------|
      |-- POST /api/conversations (run:true) -->|   # returns {id}; agent starts
      |<-- {id} ---------------------------|
      |-- WS connect /sockets/events/{id}?session_api_key=…&resend_mode=all -->|
      |                          agent runs, emits events over WS
      |<== event stream (resend_mode=all replays anything already emitted) ==|
      |<== ConversationStateUpdateEvent execution_status=running ==|
      |<== ConversationStateUpdateEvent execution_status=finished ==|
      |   *** terminal state detected — no REST polling of state ***
      |-- docker rm -f (teardown) -------->|
```

## Run it

Docker must be running.

```bash
pip install requests websockets

export LLM_API_KEY=...                     # required
export LLM_MODEL=litellm_proxy/...         # required
export LLM_BASE_URL=https://...            # optional (provider default if unset)

python watch_ws.py
```

`watch_ws.py` flags / env vars:

| Flag | Env var | Default |
|------|---------|---------|
| `--llm-api-key` | `LLM_API_KEY` | — (required) |
| `--llm-model` | `LLM_MODEL` | — (required) |
| `--llm-base-url` | `LLM_BASE_URL` | none |
| `--session-key` | `SESSION_API_KEY` | `local-demo-key` |
| `--image` | `OH_AGENT_SERVER_IMAGE` | `ghcr.io/openhands/agent-server:latest-python` |
| `--server-port` | `OH_SERVER_PORT` | `8000` |
| `--message` | — | `Say hello in one short sentence, then stop.` |
| `--watch-timeout` | — | `120` |
| `--keep` | — | off (container removed at end) |

## What it prints

```
container: 13ee756cf2cd
health: ok
conversation: 603e4620-df37-414d-af42-296dd562bfae
ws: connecting to ws://localhost:8000/sockets/events/603e4620df37414daf42296dd562bfae
ws: connected — waiting for terminal state (no REST polling)

  [event] ConversationStateUpdateEvent  execution_status=idle
  [event] SystemPromptEvent
  [event] MessageEvent
  [event] ConversationStateUpdateEvent  execution_status=running
  [event] ActionEvent
  [event] ObservationEvent
  [event] ConversationStateUpdateEvent  execution_status=finished

terminal state reached: finished
(this signal arrived over the WebSocket — no polling)
removed container oh-ws-demo
```

## Notes

- **FINISHED is a hint; ERROR/STUCK are immediate.** The SDK treats a per-field
  `finished` as advisory because a Stop hook can still revert the stop (see
  [`finish-callback`](../finish-callback/)); it waits for the post-run full-state
  snapshot to confirm. `error` and `stuck` are accepted immediately. This demo
  keeps things simple and reports the first terminal status it sees; if you need
  the authoritative confirmation, prefer the `full_state` snapshot's
  `execution_status`.
- **Cloud:** point `wss://<agent-server-url>/sockets/events/{id}` at a sandbox's
  agent-server URL and use its `session_api_key`. Everything else is identical —
  this is the Cloud-friendly way to get push notifications without webhook
  injection. (The older [oh-websocket-example](https://github.com/jpshackelford/oh-websocket-example)
  shows the **V0** socket; this uses the current **V1** agent-server socket.)
- **No conversation-state polling:** the only REST call to the server is
  `GET /health`, to learn when the *server* is up. Every conversation-state
  signal comes off the socket.
- Full agent-server schema: `http://localhost:<server-port>/openapi.json` once
  the container is healthy.

## Related

- [`react-to-state-websocket`](../react-to-state-websocket/) — the same V1
  WebSocket, but on the **Cloud** substrate and framed as "react to *every*
  `execution_status` transition." Two ways to create the conversation
  (Cloud-attach vs. agent-direct). Reach for it when you want the Cloud flow or
  to follow all transitions; reach for **this** example for the minimal,
  local, reproducible "wait for the *terminal* state and exit."
- [`react-to-state-webhooks`](https://github.com/jpshackelford/oh-examples/pull/22)
  (proposed) — the push-from-server webhook version (local-only;
  batching/retries/backpressure)
- [`server-info-idle`](../server-info-idle/) — the coarse pull version: poll
  `/server_info.idle_time` for "workspace has gone quiet"
- [`finish-callback`](../finish-callback/) — a Stop-hook callback on `FINISHED`
- [`start-sandbox`](../start-sandbox/) — how to get a Cloud sandbox's
  agent-server URL + session key (for the `wss://` path)
