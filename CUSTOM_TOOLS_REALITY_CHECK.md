# Custom Tools - The Reality Check

## The Confusion

I claimed that automation's `main.py` could define custom tools that the agent-server would import. But this doesn't make sense when you consider the process architecture!

## The Process Architecture (Ground Truth)

```
┌────────────────────────────────────────────────┐
│  Sandbox (Container/Pod)                       │
│                                                 │
│  Process 1: Agent-Server (FastAPI)             │
│    - Runs continuously                          │
│    - Serves /api/* endpoints                    │
│    - Cannot import from other processes         │
│                                                 │
│  Process 2: Automation Script (when triggered)  │
│    - bash -c "cd /work && python main.py"       │
│    - Separate Python interpreter                │
│    - Runs once, then exits                      │
│    - Cannot share Python modules with Process 1 │
└────────────────────────────────────────────────┘
```

**Key fact:** These are **separate processes** with separate Python interpreters!

## How Automation Actually Executes

From `openhands/automation/execution.py`:

```python
cmd = (
    f"mkdir -p {work_dir}"
    f" && tar xzf {tarball_path} -C {work_dir}"  # Extract to /tmp/automation-run-123
    f" && cd {work_dir}"
    f" && bash setup.sh"  # Install dependencies
    f" && {entrypoint}"   # Run: .venv/bin/python main.py
)

# Execute via agent-server's bash endpoint
await _start_bash(client, agent_url, session_key, cmd)
```

This spawns a **bash process** which spawns a **Python process**.

## The Problem with My Explanation

I said:
> "Agent-server imports the custom tool via `tool_module_qualnames`"

But if main.py runs in Process 2 and agent-server is Process 1, **agent-server cannot import modules from main.py's process!**

## What Actually Happens

Looking at automation's `sdk_main.py`:

```python
# Get default agent (built-in tools only!)
agent = get_default_agent(llm=llm, cli_mode=True)

# No custom tools are added here!

# Create conversation
conversation = Conversation(agent=agent, workspace=workspace)
```

**Automation preset does NOT use custom tools at all!**

It only uses:
- Built-in tools (terminal, file_editor, task_tracker)
- Plugins (for skills/MCP, not executable tools)
- Built-in agent functionality

## So When WOULD Custom Tools Work?

### Option 1: Client-Side Tools

Custom tools can run in the **client process** (main.py), not agent-server:

```python
# In main.py

from openhands.sdk.tool.client_tool import ClientToolSpec

# Define tool spec (JSON schema, no executor)
my_tool_spec = ClientToolSpec(
    name="my_tool",
    description="...",
    parameters={...}  # JSON schema
)

# Create agent with client tool
agent = Agent(tools=[...], client_tools=[my_tool_spec])

# Create conversation
conversation = Conversation(agent=agent, workspace=workspace)

# When agent calls my_tool, YOU handle it via callbacks
def handle_client_tool_call(event):
    if event.kind == "ActionEvent" and event.tool_name == "my_tool":
        # Execute tool in THIS process (main.py)
        result = my_custom_logic(event.action)
        # Send result back to agent-server
        conversation.send_observation(result)

conversation.callbacks.append(handle_client_tool_call)
```

**This works because:**
- Tool executes in main.py process (Process 2)
- Agent-server just knows "there's a tool called my_tool"
- When agent wants to use it, sends ActionEvent
- Client handles execution and sends back ObservationEvent

### Option 2: Tools in Agent-Server's Import Path

If you can get the tool code into agent-server's PYTHONPATH BEFORE agent-server starts:

```python
# Install tool globally in sandbox
pip install /path/to/my_custom_tool_package/

# Now agent-server can import it
# (but agent-server must restart to pick up new modules)
```

**This works but requires:**
- Tool installed before agent-server starts
- OR agent-server restart after installation
- Not practical for per-automation custom tools

### Option 3: File Upload + PYTHONPATH Manipulation

**Theoretically:**

```python
# 1. Upload tool to filesystem
POST /api/file/upload -> /workspace/my_tool.py

# 2. Run Python code that:
#    - Adds /workspace to sys.path
#    - Imports and registers tool
#    - Creates conversation
python3 << EOF
import sys
sys.path.insert(0, '/workspace')

import my_tool
from openhands.sdk.tool import register_tool
register_tool("my_tool", my_tool.MyCustomTool)

# Now create conversation...
EOF
```

**But this has problems:**
- Registration happens in bash subprocess, not agent-server
- When bash subprocess exits, registration is lost
- Still doesn't make tool available to agent-server

## The Real Answer to Your Question

> When automation uploads a tarball and runs main.py, does it create a second agent-server?

**No.** There's only ONE agent-server (always running).

> How does arbitrary agent code connect to a conversation?

**Via HTTP/WebSocket APIs.**

main.py is a **client** that:
1. Connects to existing agent-server via `RemoteWorkspace`
2. Creates `RemoteConversation` (sends `POST /api/conversations`)
3. Runs conversation (sends `POST /api/conversations/{id}/run`)
4. Agent-server executes the conversation using its own agent instance

> How do custom tools work?

**They don't - not in the way I described!**

Automation preset uses:
- **Built-in tools** (already in agent-server)
- **Client tools** (execute in main.py, not agent-server)
- **NOT custom server-side tools** (can't import from different process)

## Can We Demonstrate Custom Tools via Agent-Server?

**No, not easily, because:**

1. **Agent-server can only use tools it can import**
2. **Tools from main.py are in a different process**
3. **Importing across processes doesn't work**

**We CAN demonstrate:**
- ✅ Configuring built-in tools (custom-agent-no-browser)
- ✅ Creating custom tools locally via SDK (custom-agent-with-tool)
- ⚠️ Client-side tools (new example we could create)

**We CANNOT demonstrate (without modifying agent-server):**
- ❌ Custom server-side tools via simple API calls
- ❌ Custom tools that execute in agent-server from automation

## What Example Could We Create?

**`custom-client-side-tool/`** - Demonstrate client tool pattern:

```python
#!/usr/bin/env python3
"""Custom tool that executes in client, not agent-server."""

# 1. Create sandbox
sandbox = create_sandbox()

# 2. Define client tool spec (no executor, just schema)
my_tool_spec = ClientToolSpec(
    name="weather",
    description="Get weather for a location",
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string"}
        }
    }
)

# 3. Create agent with client tool
agent = Agent(
    llm=llm,
    tools=[Tool(name="terminal"), Tool(name="file_editor")],
)

# 4. Create conversation
workspace = RemoteWorkspace(host=agent_server, api_key=session_key)
conversation = Conversation(
    agent=agent,
    workspace=workspace,
    client_tools=[my_tool_spec]  # Tool spec sent to agent-server
)

# 5. Handle tool execution in THIS process
def handle_tool_call(event):
    if event.tool_name == "weather":
        # Execute HERE in client
        weather = get_weather(event.action.location)
        # Send result to agent-server
        return Observation(content=weather)

conversation.add_callback(handle_tool_call)

# 6. Run conversation
conversation.send_message("What's the weather in SF?")
conversation.run()

# Agent-server knows about "weather" tool
# When agent calls it, we handle execution
# Result goes back to agent for continued reasoning
```

This demonstrates custom tools that actually WORK via the APIs!

## Summary

| My Claim | Reality |
|----------|---------|
| "main.py runs in same process as agent-server" | ❌ FALSE - separate processes |
| "Agent-server imports tool from main.py" | ❌ FALSE - can't import across processes |
| "tool_module_qualnames makes it work" | ⚠️ PARTIAL - works for built-ins, not for main.py tools |
| "Automation uses custom tools" | ❌ FALSE - uses built-in tools + plugins only |

**Correct understanding:**
- Agent-server is a long-running process
- Automation scripts are separate client processes
- They communicate via HTTP/WebSocket
- Custom tools need to be either:
  - Client-side (execute in client process)
  - Pre-installed (in agent-server's import path)
  - Not practical for per-automation custom tools

I apologize for the confusion in my earlier explanation!
