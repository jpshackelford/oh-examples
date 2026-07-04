# How Custom Tools Actually Work - The Complete Architecture

## Your Question

> How does the automation approach allow execution of arbitrary agent construction, yet we still see the conversation in the app server API? Does automation bypass the agent-server? How does the arbitrary agent defined in the tarball become connected to a conversation?

## The Answer: Tool Module Qualnames

After tracing through the SDK code, here's what actually happens:

---

## The Complete Flow

### Step 1: Automation Uploads Tarball

```
Automation Service
  └─ Uploads tarball to agent-server's filesystem
  └─ Runs setup.sh (installs SDK)
  └─ Executes main.py
```

### Step 2: main.py Defines and Registers Custom Tool

```python
# Inside the uploaded main.py

from openhands.sdk.tool import register_tool

# Define custom tool
class MyCustomTool(ToolDefinition):
    # ... Action, Observation, Executor ...
    pass

# Register it
register_tool("my_custom_tool", MyCustomTool)
```

**What register_tool() does:**

```python
# From openhands/sdk/tool/registry.py

_TOOL_REGISTRY: dict[str, type[ToolDefinition]] = {}
_MODULE_QUALNAMES: dict[str, str] = {}

def register_tool(name: str, tool_class: type[ToolDefinition]):
    _TOOL_REGISTRY[name] = tool_class
    _MODULE_QUALNAMES[name] = f"{tool_class.__module__}.{tool_class.__qualname__}"
    # e.g., "my_tool" -> "main.MyCustomTool"
```

### Step 3: main.py Creates Agent with Custom Tool

```python
# Still in main.py

agent = Agent(
    llm=llm,
    tools=[
        Tool(name="terminal"),
        Tool(name="file_editor"),
        Tool(name="my_custom_tool"),  # Custom tool by name
    ]
)
```

### Step 4: main.py Creates Conversation

```python
# main.py continues...

workspace = OpenHandsCloudWorkspace(local_agent_server_mode=True, ...)

conversation = Conversation(agent=agent, workspace=workspace)
# This creates a RemoteConversation because workspace is RemoteWorkspace
```

### Step 5: RemoteConversation Sends Agent + Module Qualnames to Agent-Server

Here's the **critical code** (from `openhands/sdk/conversation/impl/remote_conversation.py`):

```python
# When creating a RemoteConversation

from openhands.sdk.tool.registry import get_tool_module_qualnames

tool_qualnames = get_tool_module_qualnames()
# Returns: {
#   "terminal": "openhands.tools.terminal.definition.TerminalTool",
#   "file_editor": "openhands.tools.file_editor.definition.FileEditorTool",
#   "my_custom_tool": "main.MyCustomTool"  # ← Custom tool!
# }

payload = {
    "agent": agent.model_dump(mode="json"),  # Serialized agent config
    "tool_module_qualnames": tool_qualnames,  # ← The magic!
    "workspace": {...},
    # ... other fields ...
}

# Send to agent-server
resp = client.post(
    "/api/conversations",  # Agent-server endpoint
    json=payload
)
```

### Step 6: Agent-Server Imports Custom Tool

**Agent-server receives the request and does:**

```python
# Inside agent-server's POST /api/conversations handler

tool_qualnames = request.json["tool_module_qualnames"]
# {
#   "terminal": "openhands.tools.terminal.definition.TerminalTool",
#   "my_custom_tool": "main.MyCustomTool"  # ← Custom tool module path
# }

# Agent-server dynamically imports the tools
for tool_name, module_qualname in tool_qualnames.items():
    module_path, class_name = module_qualname.rsplit(".", 1)
    module = importlib.import_module(module_path)  # Import main module
    tool_class = getattr(module, class_name)       # Get MyCustomTool class
    register_tool(tool_name, tool_class)            # Register in agent-server
```

**This works because:**
- `main.py` is running in the **same Python environment** as the agent-server
- When agent-server does `import main`, it finds the module
- The custom tool class is now available in the agent-server's process

### Step 7: Agent-Server Creates Conversation

```python
# Agent-server continues...

# Now agent-server can create an Agent with the custom tool
agent = Agent(
    llm=...,
    tools=[
        Tool(name="terminal"),     # Already registered (built-in)
        Tool(name="my_custom_tool") # Now registered (custom)
    ]
)

# Create conversation managed by agent-server
conversation = LocalConversation(agent=agent, workspace=workspace)

# Store conversation
conversations[conversation_id] = conversation

# Return to SDK
return {"id": conversation_id}
```

### Step 8: SDK Runs Conversation via Agent-Server APIs

```python
# Back in main.py

conversation.send_message("Use my_custom_tool to do X")
conversation.run()  
# This sends POST /api/conversations/{id}/run to agent-server

# Agent-server executes conversation using LocalConversation
# The custom tool is now available and can be called by the agent
```

---

## The Key Insight

**The custom tool code runs in the SAME Python environment as the agent-server!**

```
┌────────────────────────────────────────────────────┐
│  Python Process (inside sandbox)                   │
│                                                     │
│  ┌──────────────────────────────────────────────┐ │
│  │  main.py (automation tarball)                │ │
│  │  - Defines MyCustomTool                      │ │
│  │  - Calls register_tool("my_tool", MyCustom) │ │
│  │  - Creates RemoteConversation                │ │
│  └──────────────────────────────────────────────┘ │
│                       │                            │
│                       │ imports work because       │
│                       │ same Python process!       │
│                       ▼                            │
│  ┌──────────────────────────────────────────────┐ │
│  │  Agent-Server (FastAPI)                      │ │
│  │  - Receives tool_module_qualnames            │ │
│  │  - Imports main.MyCustomTool                 │ │
│  │  - Registers tool locally                    │ │
│  │  - Creates LocalConversation with tool       │ │
│  └──────────────────────────────────────────────┘ │
│                                                     │
└────────────────────────────────────────────────────┘
```

---

## Why This Works for Automation

1. **Automation uploads tarball to sandbox** → Files are on disk
2. **Automation runs `python main.py`** → Same Python interpreter as agent-server
3. **main.py imports work** → Module is in Python's import path
4. **main.py registers tool** → Goes into tool registry
5. **main.py creates RemoteConversation** → Sends module qualnames to agent-server
6. **Agent-server imports `main.MyCustomTool`** → Works because same process
7. **Agent-server creates conversation** → Tool is now available
8. **Conversation visible in Cloud API** → Agent-server reports it

---

## Why You CAN'T Do This via Pure API Calls

If you try to use custom tools from outside the sandbox:

```python
# From your local machine (NOT in sandbox)

agent = Agent(tools=[Tool(name="my_custom_tool")])

# Create conversation via agent-server API
workspace = RemoteWorkspace(host="https://sandbox.all-hands.dev")
conversation = Conversation(agent=agent, workspace=workspace)
```

**What happens:**

1. SDK calls `register_tool("my_custom_tool", MyCustomTool)` **locally**
2. SDK sends `tool_module_qualnames` to agent-server:
   ```python
   {"my_custom_tool": "my_script.MyCustomTool"}
   ```
3. Agent-server tries to import `my_script.MyCustomTool`
4. **FAILS** because `my_script.py` doesn't exist in agent-server's environment
5. Conversation creation fails

---

## The Missing Piece: Code Co-location

**For custom tools to work:**
- Tool definition code MUST be in agent-server's Python environment
- Tool MUST be registered before creating conversation
- Module MUST be importable by agent-server

**Two ways to achieve this:**

### Option 1: Automation Pattern (What We Discovered)
```
Upload tarball → Run in sandbox → Code co-located → Works
```

### Option 2: Custom Agent-Server Image
```dockerfile
FROM openhands/agent-server:latest
COPY my_tools/ /opt/custom_tools/
ENV PYTHONPATH=/opt/custom_tools:$PYTHONPATH
RUN python -c "from my_tools import register_all_tools; register_all_tools()"
```

---

## Can We Mimic This Without Automation APIs?

**Theoretically yes, if we can:**

1. Upload Python files to agent-server's filesystem
2. Make them importable (add to PYTHONPATH)
3. Execute registration code in agent-server's process

**The problem:** Agent-server APIs don't provide this capability.

**What we can do:**

### Approach A: Use File Upload + Bash Execution

```python
# 1. Upload custom tool file
requests.post(
    f"{agent_server}/api/file/upload",
    files={"file": open("my_tool.py", "rb")},
    # Uploads to /workspace/my_tool.py
)

# 2. Run Python code that registers and creates conversation
script = """
import sys
sys.path.insert(0, '/workspace')
import my_tool  # Import uploaded file

from openhands.sdk import Agent, Conversation, Tool
from openhands.sdk.tool import register_tool

# Register tool
register_tool("my_tool", my_tool.MyCustomTool)

# Create agent
agent = Agent(tools=[Tool(name="my_tool")])

# Create conversation
from openhands.sdk.workspace import LocalWorkspace
conversation = Conversation(agent=agent, workspace=LocalWorkspace())
conversation.send_message("Use my_tool")
conversation.run()
"""

requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    json={"command": f"python3 -c '{script}'"}
)
```

**This might work!** Because:
- Tool code is uploaded to agent-server
- Python runs in agent-server's environment  
- Can import the uploaded module
- Creates conversation in same process

---

## Example We Could Create

**`custom-tool-via-upload/`**

```python
#!/usr/bin/env python3
"""Upload custom tool to agent-server and create conversation."""

import requests

# 1. Create sandbox
sandbox = create_sandbox_via_cloud_api()
agent_server_url = sandbox["agent_server_url"]
session_key = sandbox["session_key"]

# 2. Upload custom tool Python file
with open("my_custom_tool.py", "rb") as f:
    requests.post(
        f"{agent_server_url}/api/file/upload",
        headers={"X-Session-API-Key": session_key},
        files={"file": f}
    )

# 3. Create and run conversation with custom tool
conversation_script = """
import sys
sys.path.insert(0, '/workspace')

from openhands.sdk import Agent, Conversation, Tool, LLM
from openhands.sdk.tool import register_tool
from openhands.sdk.workspace import LocalWorkspace

# Import and register custom tool
import my_custom_tool
register_tool("my_tool", my_custom_tool.MyCustomTool)

# Create agent with custom tool
llm = LLM.from_settings_file()  # Uses agent-server's LLM config
agent = Agent(llm=llm, tools=[
    Tool(name="terminal"),
    Tool(name="my_tool")  # Custom tool!
])

# Create and run conversation
conversation = Conversation(
    agent=agent,
    workspace=LocalWorkspace("/workspace")
)

conversation.send_message("Use my_tool to do something")
conversation.run()

print(f"Conversation ID: {conversation.id}")
"""

# Execute the script
requests.post(
    f"{agent_server_url}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": f"cd /workspace && python3 -c '{conversation_script}'"}
)
```

**This demonstrates:**
- Uploading custom tool code to agent-server
- Running SDK code in agent-server's environment  
- Creating conversation with custom tool
- **WITHOUT using automation APIs**

Want me to create this example?

---

## Summary

| Question | Answer |
|----------|--------|
| Does automation bypass agent-server? | **No** - it runs code that creates conversations via agent-server APIs |
| How does custom tool code connect to conversation? | Tool **module qualnames** are sent; agent-server **imports** them |
| Why does it work? | Code runs in **same Python environment** as agent-server |
| Can we do this via pure APIs? | **No** - we need code execution in agent-server's environment |
| Can we mimic it? | **Yes** - via file upload + bash execution of Python script |

The secret sauce is **`tool_module_qualnames`** - it tells agent-server which modules to import to get the tool classes!
