# Start a Sandbox (no conversation)

A ~25-line script that creates an OpenHands Cloud sandbox via the V1 API,
waits for it to reach `RUNNING`, then talks directly to the sandbox's
agent-server REST API to run shell commands.

No conversation is created — useful when you want a managed remote workspace
to drive yourself (e.g. for tooling, batch jobs, or programmatic agents).

## APIs used

### 1. Cloud App Server — manages the sandbox lifecycle

- Base URL: `https://app.all-hands.dev`
- Auth header: `X-Session-API-Key: <OH_API_KEY>`
- Endpoints:
  - `POST /api/v1/sandboxes` — start a sandbox (optional `?sandbox_spec_id=…`)
  - `GET  /api/v1/sandboxes?id=<id>` — batch-get sandboxes by id
    (returns `SandboxInfo` with `status`, `session_api_key`, `exposed_urls`, …)

### 2. Agent Server — runs inside the sandbox

- Base URL: the entry in `sandbox.exposed_urls` with `name == "AGENT_SERVER"`
  (internal port 8000, exposed publicly on a different port)
- Auth header: `X-Session-API-Key: <session_api_key>` returned by the
  sandbox-create call (different from your Cloud API key)
- All routes are under `/api/...`. This example uses:
  - `POST /api/bash/execute_bash_command` — run a bash command and wait
    for its result; body `{ "command": "...", "timeout": 30, "cwd": "..." }`,
    response includes `stdout`, `stderr`, `exit_code`

> Full Agent Server schema is available at
> `<agent_server_url>/openapi.json` once the sandbox is `RUNNING`.

## What it prints

```
sandbox: 59Ji2kvkUtZZSm7zAkAxwN
  status: RUNNING
agent: https://rzwfxneubhwcfpav.prod-runtime.all-hands.dev

=== ls -la /workspace ===
drwxr-sr-x bash_events
drwxr-sr-x conversations
drwxrws--- lost+found

=== agent-server process ===
openhan+ 1  /usr/local/bin/openhands-agent-server --port 60000
openhan+ 38 /usr/local/bin/openhands-agent-server --port 60000
```

`/workspace` is the sandbox's working tree. The agent-server is the binary
target built from the
[software-agent-sdk Dockerfile](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-agent-server/openhands/agent_server/docker/Dockerfile).
You'll see two processes: a uvicorn parent and a worker.

## Run it

```bash
export OH_API_KEY=...       # your https://app.all-hands.dev API key
pip install requests
python sandbox_demo.py
```

The script intentionally **does not** delete the sandbox at the end so you
can poke at it. Clean up with:

```bash
curl -X DELETE "https://app.all-hands.dev/api/v1/sandboxes/<sandbox_id>" \
     -H "X-Session-API-Key: $OH_API_KEY"
```

## Notes

- A freshly created sandbox starts in `STARTING`; `session_api_key` and
  `exposed_urls` are `null` until it becomes `RUNNING`. Polling every few
  seconds is sufficient.
- The Cloud API has no single-sandbox `GET /sandboxes/{id}` — use the
  batch-get endpoint `GET /sandboxes?id=<id>` and read the first item.
- To pick a specific runtime image, pass `?sandbox_spec_id=<id>` to the
  `POST /api/v1/sandboxes` call. List available specs with
  `GET /api/v1/sandbox-specs/search`.
