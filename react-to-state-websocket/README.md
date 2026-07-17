# React to conversation state changes over a WebSocket

A short script that reacts to OpenHands conversation state changes **as they
happen**, instead of polling a REST endpoint in a loop. It starts a sandbox,
opens a conversation on the sandbox's agent-server, then subscribes to that
conversation's event stream over a WebSocket and prints each
`execution_status` transition (`running` → `finished`/`error`) the moment the
agent-server emits it.

This is the event-driven counterpart to the polling loops in
[`start-sandbox`](../start-sandbox/) and [`clone-and-attach`](../clone-and-attach/),
which repeatedly `GET` the status until it changes. Here nothing polls the
*conversation* — the script blocks on the socket and is woken by the server.

> Looking to react to state changes from **outside** the sandbox (e.g. a
> service that receives an HTTP callback), rather than holding a socket open?
> That needs the agent-server's outbound **webhooks**, which can only be
> configured on an agent-server you run yourself — see the **Notes** at the
> bottom.

## APIs used

### 1. Cloud App Server — manages the sandbox lifecycle

- Base URL: `https://app.all-hands.dev`
- Auth header: `X-Session-API-Key: <OH_API_KEY>`
- Endpoints:
  - `POST /api/v1/sandboxes` — start a sandbox (optional `?sandbox_spec_id=…`)
  - `GET  /api/v1/sandboxes?id=<id>` — batch-get sandboxes by id
  - `DELETE /api/v1/sandboxes/{id}?sandbox_id=<id>` — clean up

### 2. Agent Server — runs inside the sandbox

- Base URL: the entry in `sandbox.exposed_urls` with `name == "AGENT_SERVER"`.
- Auth header: `X-Session-API-Key: <session_api_key>` returned by the
  sandbox-create call (different from your Cloud API key).
- Endpoints:
  - `POST /api/conversations` — create a conversation. The body requires a
    `workspace` and an `agent` (with an `llm`); an `initial_message` makes it
    start running immediately.
  - `GET  /sockets/events/{conversation_id}` — **WebSocket** event stream. This
    is the star of the example. Authenticate by sending
    `{"type": "auth", "session_api_key": "…"}` as the first frame. Add
    `?resend_mode=all` to replay events already produced since the conversation
    started (this closes the create→connect race without polling).

> Full Agent Server schema is at `<agent_server_url>/openapi.json` once the
> sandbox is `RUNNING`.

## The flow

```
POST /api/v1/sandboxes                          # 1. start a sandbox
GET  /api/v1/sandboxes?id=<id>                  # 2. poll until status == RUNNING
POST {agent}/api/conversations                  # 3. create conversation (auto-runs)
WS   {agent}/sockets/events/<id>?resend_mode=all # 4. subscribe + react to states
DELETE /api/v1/sandboxes/<id>?sandbox_id=<id>   # 5. clean up
```

Steps 1, 2 and 5 use the **Cloud app server** (`X-Session-API-Key: <OH_API_KEY>`).
Steps 3–4 use the sandbox's **agent server**
(`X-Session-API-Key: <session_api_key>`). See
[`start-sandbox`](../start-sandbox/) for more on the two-server split.

### Why the WebSocket instead of polling?

The agent-server emits a `ConversationStateUpdateEvent` with
`key == "execution_status"` on every transition. Subscribing means you learn
about `finished` (or `error`/`stuck`) the instant it happens, with no request
spam and no latency floor set by your poll interval. The socket also carries the
other events (`MessageEvent`, `ActionEvent`, `ObservationEvent`, …) if you want
to follow the agent's work in real time.

## What it prints

```
sandbox: 7R2qWtlDGkJHrSa6MAYC4i
  sandbox status: RUNNING
agent: https://pnefuieussllvggl.prod-runtime.all-hands.dev
conversation: e7e243fc-60ce-4744-aee7-1962addc6654

=== watching conversation state (WebSocket) ===
  .. SystemPromptEvent
  .. MessageEvent
  >> execution_status: running
  .. MessageEvent
  >> execution_status: finished
=== done ===

Cleaning up sandbox…
```

## Run it

```bash
export OH_API_KEY=...        # your https://app.all-hands.dev API key
export LLM_API_KEY=...       # key for the model the sandbox agent will call
pip install requests websockets

python watch_conversation.py
```

A conversation created directly on the agent-server does **not** inherit any
Cloud LLM credentials, so you must pass your own model + key:

```bash
python watch_conversation.py \
    --llm-model "gpt-4o-mini" \
    --llm-api-key "$LLM_API_KEY" \
    --message "List the files in /workspace/project"
```

| Flag | Env var | Default |
|------|---------|---------|
| `--api-key` | `OH_API_KEY` | — (required) |
| `--base-url` | `OH_API_BASE` | `https://app.all-hands.dev` |
| `--sandbox-spec-id` | `SANDBOX_SPEC_ID` | none (account default image) |
| `--message` | — | `Say hello, then stop.` |
| `--llm-model` | `LLM_MODEL` | `gpt-4o-mini` |
| `--llm-api-key` | `LLM_API_KEY` | — (required) |
| `--llm-base-url` | `LLM_BASE_URL` | none |
| `--poll-timeout` | `POLL_TIMEOUT` | `180` (seconds) |
| `--keep` | — | off (deletes the sandbox at the end) |

By default the sandbox is deleted when the script exits. Pass `--keep` to leave
it running and print the `DELETE` command instead.

## Notes

- **Only the sandbox is polled, and only for provisioning.** Step 2 waits for
  `RUNNING` because that is sandbox lifecycle, not conversation state. Once the
  agent-server is up, the conversation is entirely event-driven.
- **First-frame auth** keeps the session key out of the URL (and therefore out
  of reverse-proxy / load-balancer access logs). A deprecated
  `?session_api_key=…` query parameter also works but is not recommended.
- **`resend_mode=all`** makes the subscription race-free: because an
  `initial_message` starts the run at create time, some events may already exist
  before the socket connects. Replaying them means the example never misses the
  first `running`. Use `resend_mode=since&after_timestamp=…` if you have already
  fetched history over REST and only want newer events.
- **Terminal states.** The script stops at `finished`, `error`, or `stuck`. The
  full set of `ConversationExecutionStatus` values is `idle`, `running`,
  `paused`, `waiting_for_confirmation`, `finished`, `error`, `stuck`,
  `deleting`.
- **Webhooks (reacting from outside, no held-open socket).** The agent-server
  can also *push* to an HTTP endpoint you host — `POST {base_url}/conversations`
  on start/pause/resume/stop and `POST {base_url}/events/{id}` for event
  batches. That is a better fit when an external service, not a long-lived
  client, needs to react. However, those webhooks are supplied via the
  agent-server's startup config or `POST /api/init`, and **OpenHands Cloud
  sandboxes run with `deferred_init=False`** — `/api/init` returns `404` and
  there is no way to inject webhook config. So webhooks require an agent-server
  you run yourself (e.g. via Docker). The WebSocket approach in this example is
  the one that works against Cloud.
