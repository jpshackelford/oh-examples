# Custom Server-Side Tools: Understanding the Limitation

This example demonstrates **what doesn't work** when trying to create custom server-side tools via agent-server APIs, and more importantly, **why it doesn't work**.

## Educational Purpose

Rather than show you a fake "working" example, this demonstrates:

1. ✅ The most obvious approach someone would try
2. ❌ Where and how it fails
3. 💡 Why the architectural limitation exists
4. 🔄 What alternatives actually work

**This is intentionally a "failing" example to teach you about the system boundaries.**

---

## What This Example Tries to Do

1. **Upload** a custom tool definition file (`custom_tool_definition.py`) to agent-server
2. **Send** `tool_module_qualnames` telling agent-server about the tool
3. **Create** a conversation that attempts to use the custom tool
4. **Demonstrate** where it fails and explain why

---

## The Custom Tool

We define a "Rubber Duck Debugger" tool:

```python
# custom_tool_definition.py

from openhands.sdk import Action, Observation
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool

class RubberDuckAction(Action):
    code: str | None
    problem: str

class RubberDuckExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        # Generate debugging advice
        return RubberDuckObservation(advice=generate_advice(action.problem))

class RubberDuckTool(ToolDefinition):
    name = "rubber_duck"
    # ... configuration ...

# Auto-register when module is imported
register_tool("rubber_duck", RubberDuckTool)
```

This is a **complete, valid tool definition** using the correct SDK pattern.

---

## What We Attempt

### Step 1: Upload Tool File

```python
# Upload via /api/file/upload
files = {"file": open("custom_tool_definition.py", "rb")}
response = requests.post(
    f"{agent_server_url}/api/file/upload",
    headers={"X-Session-API-Key": session_key},
    files=files
)
# ✅ This succeeds - file is uploaded to /workspace/custom_tool_definition.py
```

### Step 2: Create Conversation with Tool

```python
payload = {
    "agent": {
        "tools": [
            {"name": "terminal"},
            {"name": "rubber_duck"}  # Our custom tool
        ]
    },
    "tool_module_qualnames": {
        "terminal": "openhands.tools.terminal.definition",
        "rubber_duck": "custom_tool_definition"  # Our uploaded file
    }
}

response = requests.post(
    f"{agent_server_url}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json=payload
)
# ✅ This might succeed - conversation created
```

### Step 3: Use the Tool

```python
# Send message asking to use rubber_duck tool
conversation.send_message("Use rubber_duck to debug this code...")
conversation.run()

# ❌ This fails when agent tries to actually use the tool
```

---

## Where It Fails

When agent-server tries to use the custom tool, it attempts:

```python
import importlib
importlib.import_module("custom_tool_definition")
```

**Error:**
```
ModuleNotFoundError: No module named 'custom_tool_definition'
```

---

## Why It Fails: The Process Architecture

### Two Separate Processes

```
┌────────────────────────────────────────────────┐
│  Sandbox Container                             │
│                                                 │
│  Process 1: Agent-Server (Always Running)      │
│  ├── FastAPI web server                        │
│  ├── Python: /usr/local/bin/python3            │
│  ├── sys.path:                                  │
│  │   └── /usr/local/lib/.../site-packages/     │
│  │       └── openhands.tools.* ✅ Can import   │
│  └── /workspace/ ❌ NOT in sys.path            │
│                                                 │
│  Process 2: Uploaded Files (On Disk)           │
│  └── /workspace/custom_tool_definition.py      │
│      └── Just a file, not an importable module │
└────────────────────────────────────────────────┘
```

### The Import Problem

When we send `tool_module_qualnames: {"rubber_duck": "custom_tool_definition"}`:

1. Agent-server receives this
2. Agent-server does: `importlib.import_module("custom_tool_definition")`
3. Python looks for `custom_tool_definition` in:
   - `/usr/local/lib/python3.11/site-packages/` ❌ Not there
   - Other sys.path directories ❌ Not there
   - `/workspace/` ❌ **Not in sys.path**
4. Import fails with `ModuleNotFoundError`

### Why Built-in Tools Work

```python
# This works:
tool_module_qualnames: {
    "terminal": "openhands.tools.terminal.definition"
}

# Because openhands-tools is installed via pip:
# /usr/local/lib/python3.11/site-packages/openhands/tools/terminal/definition.py ✅
```

The built-in tools are **installed Python packages**, not just files on disk.

---

## What Would Make It Work

### Option 1: Install as Python Package

**Before agent-server starts:**

```bash
# Package the tool
cd /workspace
tar -czf rubber_duck_tool.tar.gz custom_tool_definition.py setup.py

# Install it globally (as a package)
pip install rubber_duck_tool.tar.gz

# Now it's in site-packages and importable
```

**Then:**
```python
importlib.import_module("rubber_duck_tool")  # ✅ Works
```

**Problem:** Requires installing before agent-server starts, or restarting agent-server.

### Option 2: Modify PYTHONPATH

**If we could modify agent-server's environment:**

```bash
export PYTHONPATH=/workspace:$PYTHONPATH
# Restart agent-server
```

**Then:**
```python
importlib.import_module("custom_tool_definition")  # ✅ Works
```

**Problem:** We can't modify agent-server's environment variables via API.

### Option 3: Custom Agent-Server Image

**Build a Docker image:**

```dockerfile
FROM openhands/agent-server:latest
COPY custom_tools/ /opt/custom_tools/
RUN pip install /opt/custom_tools/
```

**Deploy this image instead of standard agent-server.**

**Problem:** Requires infrastructure control, not available in OpenHands Cloud.

---

## What Actually Works: Alternatives

### Alternative 1: Configure Built-in Tools ✅

**See:** `../custom-agent-no-browser/`

You CAN select which built-in tools the agent has access to:

```python
PATCH /api/settings
{
    "agent_settings_diff": {
        "tools": [
            {"name": "terminal"},
            {"name": "file_editor"}
            # No browser_tool_set!
        ]
    }
}
```

This restricts the agent to specific built-in tools.

### Alternative 2: Client-Side Tools ✅

**See:** `../custom-agent-client-side/` (if we create it)

Tools that execute in the **client process**, not agent-server:

```python
from openhands.sdk.tool.client_tool import ClientToolSpec

# Define tool spec (schema only)
rubber_duck_spec = ClientToolSpec(
    name="rubber_duck",
    description="Debugging assistant",
    parameters={...}  # JSON schema
)

# Create conversation with client tool
conversation = Conversation(
    agent=agent,
    workspace=workspace,
    client_tools=[rubber_duck_spec]
)

# Handle execution in THIS process
def handle_tool_call(event):
    if event.tool_name == "rubber_duck":
        result = execute_rubber_duck_logic(event.action)
        return ObservationEvent(content=result)

conversation.add_callback(handle_tool_call)
```

**How this works:**
- Agent-server knows "there's a tool called rubber_duck"
- When agent calls it, sends `ActionEvent` to client
- Client executes the logic in its own process
- Client sends `ObservationEvent` back to agent-server
- Agent continues with the result

**This is the recommended pattern for per-conversation custom tools!**

### Alternative 3: Local SDK Execution ✅

Run the SDK entirely on your local machine:

```python
from openhands.sdk import Agent, Conversation, LLM, Tool
from openhands.sdk.tool import register_tool

# Define and register custom tool
register_tool("rubber_duck", RubberDuckTool)

# Create agent locally
agent = Agent(
    llm=LLM(model="gpt-4", api_key=api_key),
    tools=[
        Tool(name="terminal"),
        Tool(name="rubber_duck")  # Custom tool works!
    ]
)

# Run conversation locally
conversation = Conversation(agent=agent, workspace="/tmp/workspace")
conversation.send_message("Use rubber_duck to debug...")
conversation.run()
```

**This works because:** Everything runs in the same Python process.

**Limitation:** Runs on your machine, not in Cloud sandbox.

### Alternative 4: Plugins ✅

If your tool is packaged as an OpenHands plugin:

```python
conversation = Conversation(
    agent=agent,
    workspace=workspace,
    plugins=[
        PluginSource(source="github:org/rubber-duck-plugin", ref="main")
    ]
)
```

Agent-server will:
1. Clone the plugin repository
2. Install it as a Python package (`pip install ./`)
3. Plugin's `__init__.py` calls `register_tool()`
4. Tool is now available

**This works because:** Plugin is installed as a package, making it importable.

---

## Running This Example

### Prerequisites

```bash
export OH_API_KEY=your-openhands-api-key
export LLM_API_KEY=your-llm-api-key  # Optional

pip install requests
```

### Run

```bash
cd custom-agent-with-tool
python attempt_custom_tool.py
```

### Expected Output

```
======================================================================
  Custom Tool Limitation Demonstration
======================================================================
   ℹ️  Cloud API: https://app.all-hands.dev
   ℹ️  This example will:
   ℹ️    1. Create a sandbox
   ℹ️    2. Upload custom tool code
   ℹ️    3. Attempt to use it in a conversation
   ℹ️    4. Show where and why it fails

[Step 1] Create sandbox via Cloud API
   ✅ Sandbox created
   ℹ️  Agent-server URL: https://...

[Step 2] Upload custom tool definition to agent-server
   ✅ Tool file uploaded to: /workspace/custom_tool_definition.py

[Step 3] Attempt to create conversation with custom tool
   ✅ Conversation created: abc-123
   ℹ️  But did the custom tool actually get registered?

[Step 4] Test if custom tool is actually usable
   ❌ Import error detected - agent-server couldn't import custom_tool_definition
   ℹ️  This is the expected failure!

======================================================================
  Why This Fails: The Process Architecture Limitation
======================================================================

[Detailed explanation of process isolation and import limitations]

======================================================================
  Summary
======================================================================

This example demonstrated:
  1. ✅ How to upload files to agent-server
  2. ✅ How to send tool_module_qualnames
  3. ❌ Why custom server-side tools don't work via simple upload
  4. 💡 What the architectural limitation is
  5. 💡 What alternatives exist
```

---

## Key Takeaways

### What You CAN Do ✅

- **Configure built-in tools** - Select which ones agent has access to
- **Use client-side tools** - Execute tool logic in your client process
- **Run SDK locally** - Full custom tool support on your machine
- **Use plugins** - Package tools as plugins for installation

### What You CANNOT Do ❌

- **Upload arbitrary Python file and use as server-side tool**
- **Dynamically add server-side tools via simple API calls**
- **Import modules from uploaded files in agent-server**

### Why the Limitation Exists

**Process isolation:** Agent-server and your code run in separate processes with separate Python interpreters. They don't share module namespaces.

**Security:** This isolation is intentional - it prevents arbitrary code execution in the agent-server process.

**Import requirements:** Python can only import modules that are:
1. Installed as packages (via pip)
2. In directories listed in sys.path
3. Uploaded files are neither by default

---

## Comparison to Automation

You might wonder: "Don't automation scripts use custom code?"

**Yes, but:**
- Automation scripts run in their own subprocess
- They're **clients** that connect to agent-server via HTTP/WebSocket
- They don't try to add custom server-side tools
- They use built-in tools + client-side logic

**Automation pattern:**
```
automation/main.py (subprocess)
  └── Creates RemoteConversation
      └── Connects to agent-server via HTTP
          └── Uses built-in tools (terminal, file_editor)
          └── Can use client-side tools (executes in main.py)
```

---

## Related Examples

- **custom-agent-no-browser** - Configure which built-in tools agent has
- **custom-agent-client-side** - Use client-side tools (tool executes in client)
- Local SDK examples - Run custom tools entirely locally

---

## Further Reading

- [OpenHands SDK Tool Documentation](https://docs.openhands.dev/sdk/guides/custom-tools)
- [Client-Side Tools Guide](https://docs.openhands.dev/sdk/guides/client-tools)
- [Plugin Development](https://docs.openhands.dev/sdk/guides/plugins)

---

## Questions?

This example is intentionally educational - it shows you the **boundary** of what's possible via APIs and explains why that boundary exists.

For questions about:
- **What IS possible** → See the alternatives section above
- **Architecture details** → See `../TOOL_MODULE_QUALNAMES_EXPLAINED.md`
- **Process isolation** → See `../CUSTOM_TOOLS_REALITY_CHECK.md`
