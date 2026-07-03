# Custom Agent Without Browser Tool

Create a custom agent configuration by selectively choosing which tools to include. This example shows how to build an agent that has terminal and file editing capabilities but **explicitly excludes the browser tool**.

## Why customize agent tools?

Different tasks need different capabilities. You might want to restrict tools when:

- 🔒 **Security**: Limit the agent to local operations only
- 🌐 **Environment**: Working without internet access
- 💰 **Cost**: Browser operations can be expensive (rendering, screenshots)
- 🎯 **Focus**: Code-only tasks don't need web research

## How it works

OpenHands agents are configured via the SDK's `Agent` class with explicit tool selection. When creating a conversation, you pass `agent_settings` with the tools you want:

```python
payload = {
    "initial_message": {...},
    "agent_settings": {
        "tools": [
            {"name": "bash"},         # ✅ Terminal access
            {"name": "file_editor"},  # ✅ File editing
            # ❌ No browser tool!
        ],
    },
}
```

That's it! The agent will only have access to the tools you specify.

## The full picture

This is the **same approach** the OpenHands UI uses for "Code Agent" vs "Plan Agent":

| Agent Type | Tools | What It Can Do |
|------------|-------|----------------|
| **Code Agent** (default) | `bash`, `file_editor`, `browser` | Full execution + web access |
| **Plan Agent** | `glob`, `grep`, `planning_file_editor` | Read-only planning |
| **This Example** | `bash`, `file_editor` | Code execution without web |

All three use the same `Agent` class under the hood — just different tool configurations!

## Run it

```bash
export OH_API_KEY=...        # your https://app.all-hands.dev API key
pip install requests

# Zero-config: creates a conversation with the custom agent,
# asks it to create a Python script, waits for completion,
# then cleans up.
python agent_no_browser.py
```

Sample output:

```
=== creating conversation with custom agent (no browser) ===
Task: Create a Python script called 'hello.py' that prints 'Hello, Custom Agent!' Then show me the file content to confirm it was created.

  start-task status: STARTING_CONVERSATION
  start-task status: READY
conversation: a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
  sandbox status: RUNNING

=== waiting for agent to complete task ===
  agent state: RUNNING
  agent state: RUNNING
  agent state: IDLE
  ✓ agent completed the task

=== result ===
View the conversation: https://app.all-hands.dev/conversations/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

The agent completed the task using ONLY:
  ✓ bash (terminal)
  ✓ file_editor
  ✗ NO browser tool!

=== cleanup ===
  deleted conversation a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
  deleted sandbox AbC123XyZ
```

## Verify it worked

Open the conversation URL in the output. In the conversation, you'll see:

1. ✅ The agent created the Python script using `file_editor`
2. ✅ The agent can run bash commands to verify
3. ❌ The agent has NO browser tool available (check the tools list in UI)

## Customize further

Pass `--keep` to leave the conversation open for inspection:

```bash
python agent_no_browser.py --keep
```

Or customize the task:

```bash
python agent_no_browser.py \
    --message "Create a simple REST API with Flask" \
    --keep
```

| Flag | Env var | Default | Purpose |
|------|---------|---------|---------|
| `--api-key` | `OH_API_KEY` | — (required) | Cloud API key |
| `--base-url` | `OH_API_BASE` | `https://app.all-hands.dev` | Cloud app server |
| `--message` | `INITIAL_MESSAGE` | demo task | Task for the agent |
| `--keep` | — | off | Don't delete the conversation/sandbox |
| `--poll-timeout` | `POLL_TIMEOUT` | `240` | Seconds to wait for readiness |

## Other tool combinations

You can create many different agent configurations:

**Research agent** (browser only, no execution):
```python
"tools": [
    {"name": "browser"},
    {"name": "grep"},
]
```

**Analysis agent** (read-only):
```python
"tools": [
    {"name": "grep"},
    {"name": "glob"},
]
```

**Planning agent** (use the preset):
```python
# Or just set agent_type="plan" to use the built-in planning agent
"agent_type": "plan"
```

## Key takeaway

**Custom agents are just tool configurations** — no special classes, no complex setup. Pass the tools you want, and that's exactly what the agent can use!

The OpenHands SDK makes it trivial to create specialized agents for different tasks. 🚀

## API endpoints used

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/app-conversations` | Create conversation with custom agent_settings |
| `GET /api/v1/app-conversations/start-tasks?ids=` | Poll for conversation id |
| `GET /api/v1/app-conversations?ids=` | Check agent state and sandbox status |
| `DELETE /api/v1/app-conversations/{id}` | Clean up the conversation |
| `DELETE /api/v1/sandboxes/{id}` | Clean up the sandbox |

## See also

- [`custom-agent-with-tool/`](../custom-agent-with-tool/) — Add a custom tool to the agent
- [`load-plugin/`](../load-plugin/) — Load plugins that extend agent capabilities
- [OpenHands SDK Agent documentation](https://docs.openhands.dev/sdk/arch/agent)
