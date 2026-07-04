# Agent Customization via Agent-Server APIs - Research Findings

## The Question

**Can we configure the agent-server (via direct API calls) so that when a conversation is created, it uses our custom agent configuration?**

## TL;DR Answer

**Partially, yes** - but **not for tools**. Here's what we found:

| Configuration | Agent-Server API Support | How |
|---------------|-------------------------|-----|
| **LLM settings** | ✅ Yes | `PATCH /api/settings` with `agent_settings_diff.llm` |
| **Secrets** | ✅ Yes | `PUT /api/settings/secrets/{name}` |
| **MCP servers** | ✅ Yes | `POST /api/settings/mcp-config` |
| **Agent profiles** | ✅ Yes | `POST /api/agent-profiles/{name}` |
| **Skills** | ✅ Yes | Upload to `/api/skills/` or via agent profiles |
| **Tool selection** | ❌ No | Tools are hardcoded via `get_default_tools(enable_browser=True)` |
| **Custom tools** | ⚠️ Requires code upload | Must upload SDK code as tarball or use file-based agents |

## How OpenHands/Automation Actually Works

After studying the `OpenHands/automation` codebase, here's the real pattern:

### What Automation Does

1. **Packages SDK code into a tarball**:
   ```
   tarball.tar.gz:
   ├── main.py          # SDK boilerplate (from preset template)
   ├── setup.sh         # Installs openhands-sdk
   ├── prompt.txt       # User's prompt
   ├── plugins_config.json  # (optional)
   └── repos_config.json    # (optional)
   ```

2. **Uploads tarball** to storage → gets `internal://upload-id`

3. **Creates automation record** with:
   - `tarball_path`: `internal://upload-id`
   - `entrypoint`: `.venv/bin/python main.py`

4. **When triggered**: Downloads tarball to agent-server, runs `setup.sh`, then `main.py`

5. **Inside main.py** (the critical part):
   ```python
   # Gets LLM from agent-server settings API
   llm = workspace.get_llm(profile_name=model_profile)
   
   # Gets default agent with tools controlled by cli_mode parameter
   agent = get_default_agent(llm=llm, cli_mode=True)
   # cli_mode=True → calls get_default_tools(enable_browser=False)
   # This is how browser is disabled
   
   # Creates conversation using SDK directly
   conversation = Conversation(agent=agent, workspace=workspace)
   conversation.send_message(USER_PROMPT)
   conversation.run()
   ```

### Key Finding

**Automation does NOT use `POST /api/v1/app-conversations` to create conversations.**

Instead:
- ✅ Uploads **SDK Python code** as a tarball
- ✅ Code runs **inside the sandbox**
- ✅ Creates `Agent` with specific tools via **SDK constructor**: `Agent(llm=llm, tools=[...])`
- ✅ Creates `Conversation` directly: `Conversation(agent=agent, workspace=workspace)`
- ❌ Does **NOT** call Cloud REST API
- ❌ Does **NOT** rely on `agent_settings.tools` parameter

## Agent-Server APIs for Configuration

### 1. Settings API (`PATCH /api/settings`)

**What it does**: Store LLM configuration, accessed via `workspace.get_llm()`

```bash
curl -X PATCH http://localhost:3000/api/settings \
  -H "Content-Type: application/json" \
  -d '{
    "agent_settings_diff": {
      "llm": {
        "model": "gpt-4",
        "api_key": "sk-..."
      }
    }
  }'
```

**Fields in agent_settings**:
- `llm`: LLM configuration
- (No `tools` field exists)

### 2. Agent Profiles API (`POST /api/agent-profiles/{name}`)

**What it does**: Create named agent profiles with specific configurations

```bash
curl -X POST http://localhost:3000/api/agent-profiles/my-profile \
  -H "Content-Type: application/json" \
  -d '{
    "agent_kind": "openhands",
    "llm_profile_ref": "gpt4",
    "agent": "CodeActAgent",
    "skills": [...],
    "system_message_suffix": "Custom instructions",
    "enable_sub_agents": false,
    "tool_concurrency_limit": 1
  }'
```

**Supported fields** (from `OpenHandsAgentProfile`):
- ✅ `agent`: Agent class name (default: "CodeActAgent")
- ✅ `skills`: List of embedded skills
- ✅ `skill_refs`: References to discovered skills
- ✅ `system_message_suffix`: Custom system prompt
- ✅ `condenser`: Condenser settings
- ✅ `verification`: Critic/refinement settings
- ✅ `enable_sub_agents`: Enable/disable sub-agent delegation
- ✅ `enable_switch_llm_tool`: Enable/disable LLM switching
- ✅ `tool_concurrency_limit`: Parallel tool execution
- ❌ **NO `tools` field** - cannot specify tool list

### 3. Secrets API (`PUT /api/settings/secrets/{name}`)

```bash
curl -X PUT http://localhost:3000/api/settings/secrets/MY_SECRET \
  -H "Content-Type: application/json" \
  -d '{
    "name": "MY_SECRET",
    "value": "secret-value",
    "description": "My custom secret"
  }'
```

### 4. MCP Config API (`POST /api/settings/mcp-config`)

```bash
curl -X POST http://localhost:3000/api/settings/mcp-config \
  -H "Content-Type: application/json" \
  -d '{
    "mcpServers": {
      "my-server": {
        "command": "node",
        "args": ["server.js"]
      }
    }
  }'
```

## The Tool Selection Problem

**Problem**: Tools are hardcoded in the agent-server code:

```python
# From conversation_service.py
tools = get_default_tools(enable_browser=True)
```

The `enable_browser` parameter is:
- ✅ Controllable in SDK code (automation's `cli_mode` parameter)
- ❌ **NOT exposed via any agent-server API**
- ❌ **NOT configurable via agent profiles**
- ❌ **NOT settable via /api/settings**

### Why Cloud API `agent_settings.tools` Doesn't Work

When we tested:
```json
{
  "agent_settings": {
    "tools": [
      {"name": "terminal"},
      {"name": "file_editor"}
    ]
  }
}
```

The Cloud API (`POST /api/v1/app-conversations`) accepted it but the agent-server **ignored it** because:
1. Cloud API might not pass it through to agent-server
2. Agent-server has no mechanism to receive/apply it
3. Conversations are created with hardcoded `get_default_tools(enable_browser=True)`

## How to Actually Customize Tools

### Option 1: Use Automation Preset API (Recommended)

Upload SDK code that constructs Agent with custom tools:

```python
# In your uploaded main.py
from openhands.sdk import Agent, Tool
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

agent = Agent(
    llm=llm,
    tools=[
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
        # Custom tool selection - no browser!
    ]
)
conversation = Conversation(agent=agent, workspace=workspace)
```

Then upload as tarball via automation preset API.

### Option 2: File-Based Agents

Upload an agent definition file to agent-server's `.agents/` directory:

```yaml
---
name: no-browser-agent
description: Agent without browser tools
llm_profile_ref: gpt4
agent: CodeActAgent
---
Custom agent without browser access.
```

*(Note: This still won't give you tool control - file-based agents use the same `get_default_tools()` mechanism)*

### Option 3: Custom Agent-Server Image

Build a Docker image with modified `conversation_service.py`:

```python
# Modified to read tools from config
tools_config = config.get("tools", ["terminal", "file_editor"])
tools = [Tool(name=name) for name in tools_config]
```

Deploy this as your agent-server.

## Recommendations for oh-examples

### What Our Examples Should Demonstrate

**custom-agent-no-browser**: Should honestly explain that:
- ✅ Agent profiles API can configure many agent settings
- ✅ You can set LLM, skills, system prompts, etc.
- ❌ Tool selection is **NOT currently exposed** via agent-server API
- ⚠️ To control tools, you must upload SDK code (automation pattern)

**custom-agent-with-tool**: Should show:
- ✅ How to write SDK code with custom tool
- ✅ How to package it with automation preset structure
- ⚠️ Clarify this is "how automation does it", not a simple API call

### Potential Third Example

**custom-agent-via-profile**: Demonstrate what agent-server APIs **do** support:

```bash
# 1. Create LLM profile
POST /api/profiles/gpt4

# 2. Create agent profile
POST /api/agent-profiles/custom-code-agent
{
  "llm_profile_ref": "gpt4",
  "agent": "CodeActAgent",
  "system_message_suffix": "You are a Python expert. Always write tests.",
  "enable_sub_agents": true,
  "tool_concurrency_limit": 3
}

# 3. Activate it
POST /api/agent-profiles/custom-code-agent/activate

# 4. Create conversation (uses active profile)
# ...conversation will use custom-code-agent settings
```

This shows what **actually works** today.

## Conclusion

**Answer to "can we setup a sandbox with custom agent via API calls?"**:

✅ **Yes for**: LLM, secrets, MCP servers, skills, system prompts, agent class, sub-agents
❌ **No for**: Tool selection (hardcoded)
⚠️ **Workaround**: Upload SDK code that constructs Agent with custom tools (automation pattern)

The agent-server **does have rich configuration APIs**, but **tool customization requires uploading code**.
