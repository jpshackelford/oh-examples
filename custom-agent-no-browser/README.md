# Custom Agent Without Browser Tool

This example demonstrates how to request a custom tool configuration when creating an OpenHands conversation via the Cloud REST API. We specify that we want only `terminal` and `file_editor` tools, excluding the browser.

## Why customize agent tools?

Different tasks need different capabilities. You might want to restrict tools when:

- 🔒 **Security**: Limit the agent to local operations only
- 🌐 **Environment**: Working without internet access
- 💰 **Cost**: Browser operations can be expensive (rendering, screenshots)
- 🎯 **Focus**: Code-only tasks don't need web research

## How it works

OpenHands Cloud API accepts an `agent_settings` parameter when creating conversations. You can specify which tools to include:

```python
payload = {
    "initial_message": {...},
    "agent_settings": {
        "tools": [
            {"name": "terminal"},      # ✅ Terminal access
            {"name": "file_editor"},   # ✅ File editing
            # ❌ No browser tool!
        ],
    },
}
```

**Note**: The exact behavior of tool configuration may vary by OpenHands deployment. In some cases, `agent_settings.tools` may be advisory. To verify which tools are actually available to your agent, check the conversation in the UI or query the agent-server configuration endpoint.

## The full picture (SDK)

For local SDK usage, you have full control over tools:

```python
from openhands.sdk import Agent, Tool, LLM, Conversation
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

agent = Agent(
    llm=llm,
    tools=[
        Tool(name=TerminalTool.name),     # terminal
        Tool(name=FileEditorTool.name),   # file_editor
        # No browser_tool_set
    ]
)

conversation = Conversation(agent=agent, workspace="/path/to/workspace")
```

In SDK mode, the agent gets exactly the tools you specify.

## Run it (Cloud API)

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
  execution status: running
  execution status: running
  execution status: finished
  ✓ agent completed the task

=== result ===
View the conversation: https://app.all-hands.dev/conversations/a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6

The agent completed the task.
To verify which tools were actually available, check the conversation UI.

=== cleanup ===
  deleted conversation a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6
  deleted sandbox AbC123XyZ
```

## Verify it worked

Open the conversation URL in the output. In the conversation, you can:

1. ✅ See which tools the agent used
2. ✅ Verify the agent completed the task
3. 🔍 Check the conversation configuration to see the actual tool set

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

## Agent types and tool configurations

Different OpenHands agent types use different tool sets:

| Agent Type | Typical Tools | Use Case |
|------------|---------------|----------|
| **Code Agent** (default) | `terminal`, `file_editor`, `browser_tool_set`, `task_tracker` | Full execution + web access |
| **Plan Agent** | `glob`, `grep`, `planning_file_editor` | Read-only planning |
| **Custom (SDK)** | Your choice | Specialized tasks |

When using the Cloud API, you can request specific tools via `agent_settings`, but the exact behavior depends on your deployment configuration.

## Key takeaway

**You can request custom tool configurations via the Cloud API's `agent_settings` parameter**, though the exact enforcement may vary by deployment.

For guaranteed control over tools, use the **OpenHands SDK** locally where you have full control over agent configuration. See the [SDK custom tools guide](https://docs.openhands.dev/sdk/guides/custom-tools) for details.

## API endpoints used

| Endpoint | Purpose |
|----------|---------|
| `POST /api/v1/app-conversations` | Create conversation with custom agent_settings |
| `GET /api/v1/app-conversations/start-tasks?ids=` | Poll for conversation id |
| `GET /api/v1/app-conversations?ids=` | Check execution status and sandbox status |
| `DELETE /api/v1/app-conversations/{id}` | Clean up the conversation |
| `DELETE /api/v1/sandboxes/{id}` | Clean up the sandbox |

## See also

- [`custom-agent-with-tool/`](../custom-agent-with-tool/) — Add a custom tool to the agent (SDK)
- [`load-plugin/`](../load-plugin/) — Load plugins that extend agent capabilities
- [OpenHands SDK Agent documentation](https://docs.openhands.dev/sdk/arch/agent)
- [OpenHands SDK Custom Tools guide](https://docs.openhands.dev/sdk/guides/custom-tools)
