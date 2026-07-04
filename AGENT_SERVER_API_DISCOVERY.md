# Agent-Server API Discovery - Ground Truth

## What We Discovered

By querying the **live agent-server OpenAPI spec** from conversation `1a48ffca58114f1ea50b3590b543624e`, we found:

**✅ YOU CAN CUSTOMIZE TOOLS VIA AGENT-SERVER API!**

## The APIs That Actually Work

### 1. GET /api/settings/agent-schema

Returns the schema for agent settings, showing **what can be configured**:

```bash
SESSION_KEY="..." # From conversation session_api_key
curl "https://{runtime}.prod-runtime.all-hands.dev/api/settings/agent-schema" \
  -H "X-Session-API-Key: $SESSION_KEY"
```

**Key finding**: The schema includes a `tools` field:

```json
{
  "key": "tools",
  "label": "Tools",
  "description": "Tools available to the agent.",
  "value_type": "array",
  "default": [],
  "prominence": "major"
}
```

### 2. PATCH /api/settings - Configure Default Agent

**This actually works!** We tested it live:

```bash
curl -X PATCH "https://{runtime}.prod-runtime.all-hands.dev/api/settings" \
  -H "X-Session-API-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_settings_diff": {
      "tools": [
        {"name": "terminal"},
        {"name": "file_editor"}
      ]
    }
  }'
```

**Result**:
```json
{
  "agent_settings": {
    "agent": "CodeActAgent",
    "tools": [
      {"name": "terminal", "params": {}},
      {"name": "file_editor", "params": {}}
    ]
  }
}
```

**It accepted the tools configuration!**

### 3. POST /api/conversations - Create Conversation with Custom Agent

The OpenAPI schema shows you can pass agent configuration directly:

```json
{
  "workspace": {
    "working_dir": "workspace/project",
    "kind": "LocalWorkspace"
  },
  "initial_message": {
    "content": [{"text": "Hello!"}]
  },
  "agent": {
    "llm": {
      "model": "gpt-4",
      "api_key": "sk-..."
    },
    "tools": [
      {"name": "terminal"},
      {"name": "file_editor"}
    ],
    "kind": "Agent"
  }
}
```

**Key difference from Cloud API**:
- Agent-server API: `POST /api/conversations` accepts `agent` object directly
- Cloud API: `POST /api/v1/app-conversations` accepts `agent_settings` (which may or may not be honored)

## Complete Agent-Server API Surface

From the OpenAPI spec at `https://{runtime}.prod-runtime.all-hands.dev/openapi.json`:

### Settings & Configuration

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/settings` | GET | Get current settings |
| `/api/settings` | PATCH | Update settings (supports `agent_settings_diff`) |
| `/api/settings/agent-schema` | GET | Get agent settings schema |
| `/api/settings/conversation-schema` | GET | Get conversation settings schema |
| `/api/settings/secrets` | GET | List secrets |
| `/api/settings/secrets/{name}` | PUT | Store secret |
| `/api/settings/secrets/{name}` | GET | Get secret |
| `/api/settings/secrets/{name}` | DELETE | Delete secret |

### Agent Profiles

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/agent-profiles` | GET | List agent profiles |
| `/api/agent-profiles/{name}` | POST | Create/update agent profile |
| `/api/agent-profiles/{name}` | GET | Get agent profile |
| `/api/agent-profiles/{name}` | DELETE | Delete agent profile |
| `/api/agent-profiles/{profile_id}/activate` | POST | Activate agent profile |
| `/api/agent-profiles/{name}/materialize` | POST | Dry-run resolve profile references |
| `/api/agent-profiles/{name}/rename` | POST | Rename profile |

### LLM Profiles

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/profiles` | GET | List LLM profiles |
| `/api/profiles/{name}` | POST | Create/update LLM profile |
| `/api/profiles/{name}` | GET | Get LLM profile |
| `/api/profiles/{name}` | DELETE | Delete LLM profile |
| `/api/profiles/{name}/activate` | POST | Activate LLM profile |
| `/api/profiles/{name}/rename` | POST | Rename profile |

### Conversations

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/conversations` | POST | Create conversation (can pass agent config!) |
| `/api/conversations` | GET | List conversations |
| `/api/conversations/{id}` | GET | Get conversation |
| `/api/conversations/{id}` | DELETE | Delete conversation |
| `/api/conversations/{id}/run` | POST | Run conversation |
| `/api/conversations/{id}/pause` | POST | Pause conversation |
| `/api/conversations/{id}/switch_profile` | POST | Switch agent profile |
| `/api/conversations/{id}/switch_llm` | POST | Switch LLM |
| `/api/conversations/{id}/secrets` | PATCH | Update conversation secrets |

### Deferred Init (Warm Pool)

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/init` | POST | Initialize dormant agent-server with runtime config |

## The Agent Settings Structure

From live testing, the full structure includes:

```json
{
  "agent_settings": {
    "agent": "CodeActAgent",
    "tools": [
      {"name": "terminal", "params": {}},
      {"name": "file_editor", "params": {}}
    ],
    "enable_sub_agents": false,
    "enable_switch_llm_tool": true,
    "tool_concurrency_limit": 1,
    "llm": {
      "model": "gpt-5.5",
      "api_key": "...",
      "base_url": null
    },
    "mcp_config": {
      "mcpServers": {}
    },
    "skills": [],
    "system_message_suffix": null,
    "condenser": {...},
    "verification": {...}
  }
}
```

## How This Changes Our Understanding

### Previous Belief (WRONG)
- ❌ Tools are hardcoded via `get_default_tools(enable_browser=True)`
- ❌ No API to customize tools
- ❌ Must upload SDK code as tarball

### New Reality (CORRECT)
- ✅ Tools CAN be configured via `PATCH /api/settings`
- ✅ `agent_settings.tools` exists and is writable
- ✅ When `tools: []` (empty), uses defaults
- ✅ When `tools: [...]` (non-empty), uses specified list
- ✅ Can also pass tools directly in `POST /api/conversations`

## Implications for oh-examples

### What custom-agent-no-browser Should Do

**Correct approach**:

```bash
# 1. Get session key from Cloud API
CONV=$(curl "https://app.all-hands.dev/api/v1/app-conversations?ids=$CONV_ID" \
  -H "Authorization: Bearer $OH_API_KEY")
SESSION_KEY=$(echo $CONV | jq -r '.[0].session_api_key')
AGENT_SERVER=$(echo $CONV | jq -r '.[0].conversation_url' | sed 's|/api/conversations/.*||')

# 2. Configure agent-server with custom tools
curl -X PATCH "$AGENT_SERVER/api/settings" \
  -H "X-Session-API-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent_settings_diff": {
      "tools": [
        {"name": "terminal"},
        {"name": "file_editor"}
      ]
    }
  }'

# 3. Create conversation (uses configured tools)
curl -X POST "$AGENT_SERVER/api/conversations" \
  -H "X-Session-API-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "initial_message": {
      "content": [{"text": "Create hello.py"}]
    }
  }'
```

**OR** pass tools directly:

```bash
curl -X POST "$AGENT_SERVER/api/conversations" \
  -H "X-Session-API-Key: $SESSION_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "agent": {
      "tools": [
        {"name": "terminal"},
        {"name": "file_editor"}
      ]
    },
    "initial_message": {
      "content": [{"text": "Create hello.py"}]
    }
  }'
```

## Open Questions

1. **Does Cloud API honor `agent_settings.tools`?**
   - We tested: `POST /api/v1/app-conversations` with `agent_settings.tools`
   - It was IGNORED (agent got full default toolset)
   - Question: Does Cloud API pass it through to agent-server?

2. **Default behavior when tools = []**
   - Empty array triggers `get_default_tools(enable_browser=True)`
   - How to explicitly request "no tools"? `null`? Omit the field?

3. **Tool name validation**
   - What happens if you pass invalid tool names?
   - Are they silently ignored or does it error?

4. **Lifecycle of settings**
   - Settings via PATCH /api/settings: persistent across conversations?
   - Tools in POST /api/conversations: one-time override?

## Next Steps for Examples

1. **Update custom-agent-no-browser**:
   - Show the correct pattern: Configure agent-server settings
   - OR create conversation with explicit agent.tools
   - Verify browser is actually excluded

2. **Update custom-agent-with-tool**:
   - Register custom tool on agent-server
   - Include in tools array
   - Test that it works

3. **Create comprehensive example**:
   - Demonstrate full agent-server configuration workflow
   - LLM profiles → Agent profiles → Settings → Conversations
   - Show what actually works vs. what doesn't

## Sandbox Info

**This conversation's sandbox**:
- Conversation ID: `1a48ffca58114f1ea50b3590b543624e`
- Sandbox ID: `2ueOd9wbc71UaCyJT9jK14`
- Agent-server URL: `https://awpgmfsimzvsbiyn.prod-runtime.all-hands.dev`
- OpenAPI: `https://awpgmfsimzvsbiyn.prod-runtime.all-hands.dev/openapi.json`

**Verified working**:
- ✅ `GET /api/settings/agent-schema`
- ✅ `PATCH /api/settings` with `agent_settings_diff.tools`
- ⏳ `POST /api/conversations` with custom tools (needs testing)
