# How tool_module_qualnames Actually Works

## The Question

If automation's `main.py` runs in a separate process from agent-server, how does `tool_module_qualnames` allow custom tools to work?

## The Short Answer

**It doesn't - not for arbitrary custom tools.**

`tool_module_qualnames` only works for tools in **installed Python packages** that agent-server can import.

---

## The Detailed Explanation

### What tool_module_qualnames Contains

When SDK sends `tool_module_qualnames` to agent-server:

```json
{
  "tool_module_qualnames": {
    "terminal": "openhands.tools.terminal.definition",
    "file_editor": "openhands.tools.file_editor.definition",
    "my_custom_tool": "main.MyCustomTool"
  }
}
```

### What Agent-Server Does

```python
# From openhands/agent_server/conversation_service.py

for tool_name, module_qualname in request.tool_module_qualnames.items():
    try:
        importlib.import_module(module_qualname)
        # ↑ This imports the MODULE, triggering auto-registration
        logger.debug(f"Tool '{tool_name}' registered via module '{module_qualname}'")
    except ImportError as e:
        logger.warning(f"Failed to import module '{module_qualname}': {e}")
```

### When Does Import Succeed?

**Case 1: Built-in Tools** ✅

```python
importlib.import_module("openhands.tools.terminal.definition")
```

**This works because:**
- `openhands-tools` package is installed via pip
- Located in agent-server's Python environment
- In Python's sys.path: `/usr/local/lib/python3.11/site-packages/openhands/tools/`

**Case 2: Custom Tools in Installed Packages** ✅

```python
importlib.import_module("my_custom_tools.weather")
```

**This works IF:**
- `my_custom_tools` is installed via pip: `pip install my-custom-tools`
- OR it's in PYTHONPATH: `PYTHONPATH=/path/to/my_custom_tools`
- Package is accessible to agent-server's Python interpreter

**Case 3: Custom Tools in main.py** ❌

```python
importlib.import_module("main")  # or "__main__"
```

**This FAILS because:**
- main.py is at `/tmp/automation-run-123/main.py`
- That directory is NOT in agent-server's sys.path
- Agent-server's Python can't find the "main" module
- Import fails with: `ModuleNotFoundError: No module named 'main'`

---

## Why Built-in Tools Work

Built-in tools have auto-registration code in their module:

```python
# openhands/tools/terminal/definition.py (end of file)

from openhands.sdk.tool import register_tool

class TerminalTool(ToolDefinition):
    # ... tool definition ...
    pass

# Auto-register when module is imported
register_tool(TerminalTool.name, TerminalTool)
```

**The flow:**

1. Client sends: `{"terminal": "openhands.tools.terminal.definition"}`
2. Agent-server does: `importlib.import_module("openhands.tools.terminal.definition")`
3. Import executes the module code
4. Module code calls `register_tool("terminal", TerminalTool)`
5. Tool is now in agent-server's tool registry
6. Agent can use the tool

---

## Why Automation Can't Use Custom Tools This Way

**What automation does:**

```bash
# Execute via /api/bash/start_bash_command
cd /tmp/automation-run-123
python3 -m venv .venv
.venv/bin/pip install openhands-sdk
.venv/bin/python main.py
```

**Where main.py is located:**
- `/tmp/automation-run-123/main.py`

**Agent-server's sys.path does NOT include:**
- `/tmp/automation-run-123/`

**So when agent-server tries:**
```python
importlib.import_module("main")  # FAILS
```

**Error:**
```
ModuleNotFoundError: No module named 'main'
```

---

## How Could We Make It Work?

### Option 1: Install Tool as Package

**In setup.sh:**
```bash
#!/bin/bash
pip install openhands-sdk

# Install custom tool package
pip install ./my_custom_tool/
```

**Package structure:**
```
my_custom_tool/
├── pyproject.toml
├── my_custom_tool/
│   ├── __init__.py
│   └── weather.py  # Contains WeatherTool class + register_tool() call
```

**In main.py:**
```python
# Send module qualname
tool_qualnames = {
    "weather": "my_custom_tool.weather"
}

# Agent-server can now import it!
importlib.import_module("my_custom_tool.weather")  # ✅ Works
```

**Why this works:**
- pip installs package to `.venv/lib/python3.11/site-packages/my_custom_tool/`
- BUT: main.py uses its own venv (`.venv/bin/python`)
- Agent-server uses system Python or different venv
- Still doesn't work! They have different site-packages!

### Option 2: Install Globally

**In setup.sh:**
```bash
#!/bin/bash
# Install to SYSTEM Python (not venv)
python3 -m pip install --user ./my_custom_tool/

# This installs to ~/.local/lib/python3.11/site-packages/
```

**Why this MIGHT work:**
- If agent-server's Python also looks in `~/.local/`
- Then both can import the package
- But this pollutes the global environment

### Option 3: Modify PYTHONPATH

**In automation execution:**
```bash
export PYTHONPATH=/tmp/automation-run-123:$PYTHONPATH
# Now both main.py and agent-server can import "main"
```

**But there's no way to do this via APIs!**

The automation service runs the command via `/api/bash/start_bash_command`, and environment variables set there don't affect agent-server's process.

---

## What Automation Actually Uses

Looking at `automation/presets/prompt/sdk_main.py`:

```python
# Get default agent with built-in tools only
agent = get_default_agent(llm=llm, cli_mode=True)
```

**This creates an agent with:**
- `terminal` (built-in)
- `file_editor` (built-in)
- `task_tracker` (built-in)
- NO custom tools!

**Automation does NOT attempt to use custom tools via tool_module_qualnames.**

---

## The Real Purpose of tool_module_qualnames

It's designed for:

1. **Built-in tools** - Always available, always importable
2. **Tool discovery** - SDK tells agent-server "I used these tools, please ensure they're registered"
3. **Lazy loading** - Agent-server can import tool modules on-demand
4. **Plugin tools** - Tools from plugins that are installed as packages

**It's NOT designed for:**
- Arbitrary Python files
- Per-automation custom tools
- Code in automation tarball

---

## Example: When It Works

**Scenario:** Plugin that provides a custom tool

```bash
# Plugin structure (in GitHub repo)
openhands-weather-plugin/
├── pyproject.toml
├── openhands_weather_plugin/
│   ├── __init__.py
│   ├── weather_tool.py  # Tool definition + register_tool()
│   └── skills/          # Skills for context
```

**Automation loads it:**
```python
# In main.py
conversation = Conversation(
    agent=agent,
    workspace=workspace,
    plugins=[PluginSource(source="github:org/openhands-weather-plugin")]
)
```

**What happens:**
1. Agent-server fetches plugin from GitHub
2. Installs it: `pip install ./openhands-weather-plugin/`
3. Plugin's `__init__.py` calls `register_tool("weather", WeatherTool)`
4. Tool is now available

**This works because:**
- Plugin is installed as a Python package
- Package is in agent-server's import path
- Can be imported by agent-server

---

## Example: When It Doesn't Work

**Scenario:** Custom tool in automation's main.py

```python
# main.py in automation tarball

from openhands.sdk.tool import register_tool

class MyCustomTool(ToolDefinition):
    # ... tool definition ...
    pass

register_tool("my_tool", MyCustomTool)

# Create agent
agent = Agent(tools=[Tool(name="my_tool")])
conversation = Conversation(agent=agent, workspace=workspace)
```

**What happens:**
1. main.py runs in subprocess: `.venv/bin/python main.py`
2. `register_tool()` registers tool in main.py's process
3. `get_tool_module_qualnames()` returns `{"my_tool": "__main__"}`
4. SDK sends to agent-server: `{"tool_module_qualnames": {"my_tool": "__main__"}}`
5. Agent-server tries: `importlib.import_module("__main__")`
6. **FAILS** - `__main__` is main.py's module, not importable by agent-server

---

## The Right Way: Client-Side Tools

For per-conversation custom tools, use **client tools**:

```python
# main.py

from openhands.sdk.tool.client_tool import ClientToolSpec

# Define tool schema (no executor)
weather_spec = ClientToolSpec(
    name="weather",
    description="Get weather for a location",
    parameters={
        "type": "object",
        "properties": {
            "location": {"type": "string"}
        }
    }
)

# Create conversation with client tool
conversation = Conversation(
    agent=agent,
    workspace=workspace,
    client_tools=[weather_spec]  # Spec sent to agent-server
)

# Handle execution in THIS process (main.py)
def handle_tool_call(event):
    if event.kind == "ActionEvent" and event.tool_name == "weather":
        result = get_weather_from_api(event.action.location)
        # Agent-server will receive this as an observation
        return result

conversation.add_callback(handle_tool_call)
```

**This works because:**
- Agent-server knows "there's a tool called weather"
- When agent wants to use it, sends ActionEvent
- Client (main.py) executes the tool
- Client sends back ObservationEvent
- No need for agent-server to import anything

---

## Summary Table

| Tool Location | Module Qualname | Agent-Server Import | Works? |
|---------------|----------------|---------------------|---------|
| `openhands.tools.terminal` | `openhands.tools.terminal.definition` | ✅ Success | ✅ Yes |
| Installed plugin package | `my_plugin.weather` | ✅ Success (if installed) | ✅ Yes |
| automation main.py | `__main__` or `main` | ❌ Fails (not in path) | ❌ No |
| Client-side tool | N/A (no import needed) | N/A (client executes) | ✅ Yes |

---

## Conclusion

**tool_module_qualnames is for tool discovery, not arbitrary code execution.**

It tells agent-server: "Here are the modules that contain tools I want to use. Please import them so they're registered."

**It works when:**
- Modules are installed Python packages
- Packages are in agent-server's Python path
- Modules auto-register tools on import

**It doesn't work when:**
- Tool is in a standalone script (main.py)
- Script is not in agent-server's import path
- Different processes have different sys.paths

**For automation custom tools, use client-side tools instead.**
