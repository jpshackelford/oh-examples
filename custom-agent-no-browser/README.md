# Custom Agent Configuration via Agent-Server API

This example demonstrates **the correct pattern** for customizing agent tools using the OpenHands agent-server API.

## What This Example Shows

✅ **How to configure an agent-server with custom tools** (excluding browser)  
✅ **Two different approaches** for specifying tools  
✅ **Verification** that the configuration actually works  
✅ **The complete workflow** from sandbox creation to cleanup  

## The Key Insight

**You cannot configure tools via the Cloud API alone.**

The Cloud API (`POST /api/v1/app-conversations`) accepts an `agent_settings` parameter, but it is **not honored** by the agent-server. To actually customize tools, you must:

1. **Get the agent-server URL and session key** from the Cloud API
2. **Call the agent-server API directly** to configure tools
3. **Use one of two methods** (described below)

## Two Methods for Customizing Tools

### Method 1: Configure Agent-Server Settings (Recommended)

**Use `PATCH /api/settings` to set default tools for the entire agent-server instance:**

```python
# Configure the agent-server with custom tools
requests.patch(
    f"{agent_server_url}/api/settings",
    headers={"X-Session-API-Key": session_key},
    json={
        "agent_settings_diff": {
            "tools": [
                {"name": "terminal"},
                {"name": "file_editor"},
                {"name": "task_tracker"}
            ]
        }
    }
)

# Create conversation - tools come from settings, but LLM config is still required
requests.post(
    f"{agent_server_url}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json={
        "agent": {
            "llm": {
                "model": "litellm_proxy/claude-sonnet-4-5-20250929",
                "api_key": os.getenv("LLM_API_KEY"),
                "base_url": os.getenv("LLM_BASE_URL"),
            }
        },
        "workspace": {"working_dir": "/workspace"},
        "initial_message": {"content": [{"text": "Hello!"}]}
    }
)
```

**Pros:**
- Tools apply to all future conversations on this agent-server
- Cleaner conversation creation (no need to repeat tools)

**Cons:**
- Stateful - settings persist across conversations
- Must remember to configure before first conversation
- Still requires LLM config in each conversation request

### Method 2: Pass Tools Inline (Per-Conversation)

**Pass tools directly when creating each conversation:**

```python
requests.post(
    f"{agent_server_url}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json={
        "agent": {
            "llm": {
                "model": "litellm_proxy/claude-sonnet-4-5-20250929",
                "api_key": os.getenv("LLM_API_KEY"),
                "base_url": os.getenv("LLM_BASE_URL"),
            },
            "tools": [
                {"name": "terminal"},
                {"name": "file_editor"},
                {"name": "task_tracker"}
            ]
        },
        "workspace": {"working_dir": "/workspace"},
        "initial_message": {"content": [{"text": "Hello!"}]}
    }
)
```

**Pros:**
- Explicit per-conversation control
- No shared state between conversations

**Cons:**
- Must repeat tools for each conversation
- More verbose

## Usage

### Prerequisites

```bash
pip install requests

# OpenHands Cloud API key (for sandbox management)
export OH_API_KEY=your-cloud-api-key

# OpenHands LLM API key (get from Profile -> API Keys)
export LLM_API_KEY=your-llm-api-key

# LiteLLM proxy URL (default works for OpenHands Cloud)
export LLM_BASE_URL=https://llm-proxy.app.all-hands.dev/
```

**Important:** When using the agent-server API directly, you must provide both
`LLM_API_KEY` and `LLM_BASE_URL`. The agent-server needs to know where to send
LLM requests and how to authenticate with the LiteLLM proxy.

### Run with Settings Method (Default)

```bash
python agent_no_browser.py
```

Output:
```
=== Creating sandbox via Cloud API ===
  conversation: abc123...
  waiting for sandbox...
  ✓ sandbox ready: 2ueOd9wbc71U...
  agent-server: https://xxx.prod-runtime.all-hands.dev
  cleaned up temp conversation

=== Configuring agent-server with custom tools ===
  ✓ configured 3 tools:
    - terminal
    - file_editor
    - task_tracker
  ✓ browser_tool_set successfully excluded

=== Creating conversation (method: settings) ===
  using tools from agent-server settings
  ✓ conversation created: def456...

=== Running conversation ===
  conversation started
  waiting for completion...
    execution_status: running
    execution_status: finished
  ✓ conversation completed successfully

=== Verifying tools ===

  Available tools:
  total tools: 7

  🔧 Core tools (5):
    • terminal
    • file_editor
    • task_tracker
    • finish
    • think

  🔌 Create tools (1):
    • default_create_pr

  🔌 Tavily tools (1):
    • default_tavily_tavily_search

  ✅ PASS: No browser tools in available tools list

  Tools actually used: ['file_editor', 'terminal']
  ✅ PASS: No browser tools were used

=== Results ===
View conversation: https://app.all-hands.dev/conversations/def456...
```

### Run with Inline Method

```bash
python agent_no_browser.py --method inline
```

This passes tools directly in the conversation creation request instead of configuring the agent-server first.

### Keep Resources for Inspection

```bash
python agent_no_browser.py --keep
```

This skips cleanup so you can inspect the conversation in the UI.

## How It Works

### 1. Create Sandbox via Cloud API

```python
response = requests.post(
    "https://app.all-hands.dev/api/v1/app-conversations",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"github_token": None, "selected_repository": None}
)
```

This gives us:
- `sandbox_id`: Unique sandbox identifier
- `session_api_key`: Authentication for agent-server API
- `conversation_url`: Contains agent-server URL

### 2. Configure Agent-Server

**Method 1** (Settings):
```python
requests.patch(
    f"{agent_server_url}/api/settings",
    headers={"X-Session-API-Key": session_key},
    json={"agent_settings_diff": {"tools": [...]}}
)
```

**Method 2** (Inline): Skip this step

### 3. Create Conversation

**Method 1** (Settings):
```python
requests.post(
    f"{agent_server_url}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json={"initial_message": {...}}
)
```

**Method 2** (Inline):
```python
requests.post(
    f"{agent_server_url}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json={
        "agent": {"tools": [...]},
        "initial_message": {...}
    }
)
```

### 4. Run Conversation

```python
requests.post(
    f"{agent_server_url}/api/conversations/{conv_id}/run",
    headers={"X-Session-API-Key": session_key}
)
```

### 5. Verify Tools

The script now performs comprehensive tool verification:

**a) Get available tools from SystemPromptEvent:**

```python
# Get the actual tools that were configured for the agent
response = requests.get(
    f"{agent_server_url}/api/conversations/{conv_id}/events/search?kind__eq=SystemPromptEvent&limit=1",
    headers={"X-Session-API-Key": session_key}
)

system_event = response.json()["items"][0]
available_tools = system_event["tools"]

# Check if browser tools are in the list
has_browser = any(
    "browser" in tool.get("title", "").lower() 
    for tool in available_tools
)
```

**b) Check which tools were actually used:**

```python
response = requests.get(
    f"{agent_server_url}/api/conversations/{conv_id}/events/search",
    headers={"X-Session-API-Key": session_key}
)

tools_used = {
    event["tool_name"] 
    for event in response.json()["items"]
    if event.get("kind") == "ActionEvent"
}
```

The script displays tools grouped by category for easy verification:

```
Available tools:
  total tools: 7

  🔧 Core tools (5):
    • terminal
    • file_editor
    • task_tracker
    • finish
    • think

  🔌 Create tools (1):
    • default_create_pr

  ✅ PASS: No browser tools in available tools list

Tools actually used: ['file_editor', 'terminal']
  ✅ PASS: No browser tools were used
```

## Available Tools

Common tool names you can include:

- `terminal` - Execute bash commands
- `file_editor` - Read/write/edit files
- `task_tracker` - Track tasks and progress
- `browser_tool_set` - Web browser automation (excluded in this example)

## Key Agent-Server APIs Used

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/settings` | PATCH | Configure default agent settings |
| `/api/settings/agent-schema` | GET | Get schema of configurable settings |
| `/api/conversations` | POST | Create conversation (can pass agent config) |
| `/api/conversations/{id}/run` | POST | Start conversation execution |
| `/api/conversations/{id}` | GET | Get conversation status |
| `/api/conversations/{id}/events/search` | GET | Get conversation events |

## Common Issues

### "Unauthorized" error

Make sure you're using the **session API key** from the conversation, not your Cloud API key:

```python
# ✗ Wrong - Cloud API key
headers = {"Authorization": f"Bearer {cloud_api_key}"}

# ✓ Correct - Session API key
headers = {"X-Session-API-Key": session_key}
```

### Browser still appears

If browser tools still appear in the conversation:

1. **Check configured tools**: GET `/api/settings` and verify `agent_settings.tools`
2. **Check tool verification**: Look at the script output for "tools actually used"
3. **Try inline method**: Pass tools directly in conversation creation

### Conversation never finishes

The default timeout is 3 minutes (180 seconds). If your task is complex:

1. Check the conversation in the UI: `https://app.all-hands.dev/conversations/{conv_id}`
2. Look at events: GET `/api/conversations/{conv_id}/events/search`
3. Consider increasing the timeout or making the task simpler

## Architecture Notes

### Cloud API vs Agent-Server API

```
┌─────────────────────────────────────────────────────────┐
│  Cloud API (app.all-hands.dev)                         │
│  - User authentication                                   │
│  - Sandbox lifecycle (create/delete)                     │
│  - High-level conversation management                    │
└─────────────────────────────────────────────────────────┘
                        │
                        │ creates
                        ▼
┌─────────────────────────────────────────────────────────┐
│  Agent-Server (sandbox-specific runtime URL)            │
│  - Agent configuration (LLM, tools, settings)           │
│  - Conversation execution                                │
│  - Direct agent control                                  │
└─────────────────────────────────────────────────────────┘
```

**Key insight**: Agent customization happens at the **agent-server level**, not via Cloud API parameters.

### Why Cloud API Doesn't Control Tools

The Cloud API's `POST /api/v1/app-conversations` endpoint has an `agent_settings` parameter, but:

1. It's **not passed through** to the agent-server in the current deployment
2. The agent-server has its own **independent settings** via `/api/settings`
3. Tool configuration **must be done via agent-server API** for it to take effect

This is by design - the agent-server is the authoritative source for agent configuration.

## Next Steps

- See `../custom-agent-with-tool/` for adding custom tools (requires SDK)
- See `AGENT_SERVER_API_DISCOVERY.md` for full agent-server API reference
- See `AGENT_CUSTOMIZATION_FINDINGS.md` for research notes

## Related Documentation

- [OpenHands SDK Guide](https://docs.openhands.dev/sdk)
- [Agent Profiles](https://docs.openhands.dev/sdk/guides/agent-settings)
- [Custom Tools](https://docs.openhands.dev/sdk/guides/custom-tools)
