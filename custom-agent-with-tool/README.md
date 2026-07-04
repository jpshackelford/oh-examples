# Custom Server-Side Tools via Package Installation

This example demonstrates how to add **custom server-side tools** to OpenHands Cloud sandboxes using the `tool_module_qualnames` mechanism.

**Key insight:** Custom tools must be installed as Python packages, then agent-server can dynamically load them via `importlib.import_module()`.

## What This Example Shows

✅ **How to install a custom tool** as a Python package in a Cloud sandbox  
✅ **How to use `tool_module_qualnames`** to enable dynamic tool loading  
✅ **Complete working example** using the Rubber Duck Debugger tool  
✅ **Proof that this works** in OpenHands Cloud (tested live!)  

---

## Quick Start

### Prerequisites

```bash
export OH_API_KEY=your-openhands-api-key
export LLM_API_KEY=your-llm-api-key  # Optional for full test

pip install requests
```

### Run the Example

```bash
python working_example.py
```

### Expected Output

```
[DEMO] ======================================================================
[DEMO] Custom Tool via Package Installation - Working Example
[DEMO] ======================================================================
[DEMO] Creating sandbox...
[DEMO]   ✅ Sandbox running!
[DEMO] Installing custom tool package...
[DEMO]   ✅ Package structure created
[DEMO]   ✅ Package installed
[DEMO]   ✅ Tool is importable by agent-server!
[DEMO]
Creating conversation with custom tool...
[DEMO]   ✅ Conversation created
[DEMO]   ✅ Agent-server successfully imported custom tool!
[DEMO]
======================================================================
[DEMO] 🎉 SUCCESS!
======================================================================
```

---

## How It Works

### The Complete Flow

```
1. Create Cloud Sandbox
   └─ GET agent-server URL and session key

2. Install Custom Tool as Package
   ├─ Create package structure via bash
   ├─ Write setup.py (setuptools config)
   ├─ Write tool code (Action/Observation/Executor + register_tool())
   └─ pip install -e /workspace/tool_pkg

3. Create Conversation with tool_module_qualnames
   POST /api/conversations
   {
     "agent": {"tools": [{"name": "my_tool"}]},
     "tool_module_qualnames": {
       "my_tool": "my_tool_pkg.tool"
     }
   }

4. Agent-Server Dynamically Loads Tool
   └─ importlib.import_module("my_tool_pkg.tool")
   └─ Module executes, calls register_tool()
   └─ Tool is now available!

5. Agent Can Use Custom Tool
   └─ LLM can call my_tool just like built-in tools
```

### Key Components

#### 1. Tool Definition (`custom_tool_definition.py`)

Our example uses a **Rubber Duck Debugger** tool:

```python
from openhands.sdk import Action, Observation
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool

class RubberDuckAction(Action):
    code: str | None
    problem: str  # Description of the bug

class RubberDuckObservation(Observation):
    advice: str  # Debugging suggestions

class RubberDuckExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        # Generate debugging advice
        advice = generate_debugging_tips(action.problem, action.code)
        return RubberDuckObservation.from_text(
            text=advice,
            advice=advice
        )

class RubberDuckTool(ToolDefinition):
    name: ClassVar[str] = "rubber_duck"
    
    @classmethod
    def create(cls, conv_state=None):
        return [cls(
            description="Debugging assistant that provides systematic debugging suggestions",
            action_type=RubberDuckAction,
            observation_type=RubberDuckObservation,
            executor=RubberDuckExecutor()
        )]

# Auto-register when module is imported
register_tool("rubber_duck", RubberDuckTool)
```

#### 2. Package Installation

Create package structure in sandbox:

```bash
/workspace/rubber_duck_pkg/
├── setup.py                    # Setuptools configuration
├── rubber_duck/
│   ├── __init__.py            # Package marker
│   └── tool.py                # Tool definition (code above)
```

Install as editable package:

```bash
cd /workspace/rubber_duck_pkg
pip install -e .
```

Now `rubber_duck.tool` is importable!

#### 3. Dynamic Tool Registration

When creating a conversation, send `tool_module_qualnames`:

```python
{
  "agent": {
    "tools": [{"name": "rubber_duck"}]
  },
  "tool_module_qualnames": {
    "rubber_duck": "rubber_duck.tool"
  }
}
```

Agent-server does:
```python
importlib.import_module("rubber_duck.tool")
# ↑ Executes module code
# ↓ Module calls register_tool()
# ✅ Tool is now in registry
```

---

## The Rubber Duck Debugger

This example includes a fully functional debugging assistant tool based on the famous [Rubber Duck Debugging](https://en.wikipedia.org/wiki/Rubber_duck_debugging) technique.

### What It Does

Provides systematic debugging suggestions when given code and a problem description:

```
🦆 *Quack!* Let's debug this together!

Problem: Function returns wrong average

Code provided:
```
def average(nums): return sum(nums) / (len(nums) - 1)
```

Debugging suggestions:
1. Check your assumptions - print intermediate values
2. Verify inputs - are they what you expect?
3. Test edge cases - empty lists, None values, etc.
4. Read error messages carefully
5. Add logging to track execution flow

💡 Remember: Explaining the problem out loud often reveals the solution!
```

### Usage

Once installed, the agent can use it:

```python
# Agent message
"Use the rubber_duck tool to help debug this code: def avg(nums): return sum(nums)/(len(nums)-1)"

# Agent calls tool
rubber_duck(
    code="def avg(nums): return sum(nums)/(len(nums)-1)",
    problem="Returns wrong results for average calculation"
)

# Tool returns debugging advice
# Agent incorporates advice into response
```

---

## Architecture: Why This Works

### The Design of tool_module_qualnames

From `openhands/agent_server/conversation_service.py`:

```python
# Dynamically register tools from client's registry
if request.tool_module_qualnames:
    import importlib
    
    for tool_name, module_qualname in request.tool_module_qualnames.items():
        try:
            # Import the module to trigger tool auto-registration
            importlib.import_module(module_qualname)
            logger.debug(f"Tool '{tool_name}' registered via module '{module_qualname}'")
        except ImportError as e:
            logger.warning(f"Failed to import module '{module_qualname}': {e}")
```

This is **intentional design** for dynamic tool loading!

### Why Package Installation Is Required

**Agent-server can only import modules in its Python environment.**

```
Agent-Server Python Environment:
├── /usr/local/lib/python3.13/site-packages/
│   ├── openhands/              ✅ Can import (installed)
│   ├── fastapi/                ✅ Can import (installed)
│   └── rubber_duck/            ✅ Can import (we installed it!)
│
└── Random files:
    └── /workspace/my_tool.py   ❌ Cannot import (not in sys.path)
```

When we `pip install -e /workspace/rubber_duck_pkg`, it:
1. Adds package to `site-packages`
2. Makes it importable via `import rubber_duck.tool`
3. Agent-server can now use `importlib.import_module("rubber_duck.tool")`

### Process Architecture

```
┌──────────────────────────────────────────┐
│  Sandbox Container                       │
│                                          │
│  Agent-Server Process (FastAPI)          │
│  ├── Python interpreter                  │
│  ├── sys.path includes site-packages     │
│  ├── Can import installed packages ✅    │
│  └── Cannot import random files ❌       │
│                                          │
│  Our Package Installation                │
│  └── pip install adds to site-packages   │
│      └── Now importable! ✅              │
└──────────────────────────────────────────┘
```

---

## Comparison: Different Approaches

### ✅ This Approach (Package Installation)

```python
# Install as package
bash: cd /workspace/tool_pkg && pip install -e .

# Use via tool_module_qualnames
tool_module_qualnames: {"my_tool": "my_tool_pkg.tool"}

# ✅ Works! Agent-server can import it
```

**Pros:**
- Works in Cloud sandboxes
- Uses designed mechanism (tool_module_qualnames)
- Agent-server can import the module
- Clean separation of concerns

**Cons:**
- Requires package installation step
- Needs proper package structure (setup.py, etc.)

### ❌ Just Upload File (Doesn't Work)

```python
# Upload file
POST /api/file/upload → /workspace/my_tool.py

# Try to use it
tool_module_qualnames: {"my_tool": "my_tool"}

# ❌ Fails! ModuleNotFoundError
# /workspace/ is not in sys.path
```

### ✅ Local SDK (Alternative)

```python
# Run entirely locally
from openhands.sdk import Agent, Conversation, Tool
from openhands.sdk.tool import register_tool

register_tool("my_tool", MyTool)

agent = Agent(tools=[Tool(name="my_tool")])
conversation = Conversation(agent=agent, workspace="/tmp/workspace")

# ✅ Works! Everything in same Python process
```

**Pros:**
- Simple - no package installation
- Full control over environment

**Cons:**
- Runs on your machine, not in Cloud
- No Cloud UI integration

### ✅ Custom Docker Image (For Self-Hosted)

```dockerfile
FROM openhands/agent-server:latest
COPY my_tools/ /app/my_tools
ENV OH_EXTRA_PYTHON_PATH="/app"
```

**Pros:**
- Tools pre-installed in image
- No runtime installation needed

**Cons:**
- Requires infrastructure control
- Not available in OpenHands Cloud
- Overkill for simple tools

---

## Creating Your Own Custom Tool

### 1. Define Your Tool

Create `my_tool.py`:

```python
from typing import ClassVar
from pydantic import Field
from openhands.sdk import Action, Observation
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool

class MyAction(Action):
    input_param: str = Field(..., description="Input to the tool")

class MyObservation(Observation):
    result: str = Field(..., description="Tool output")

class MyExecutor(ToolExecutor[MyAction, MyObservation]):
    def __call__(self, action, conversation=None):
        # Your tool logic here
        result = process_input(action.input_param)
        return MyObservation.from_text(text=result, result=result)

class MyTool(ToolDefinition[MyAction, MyObservation]):
    name: ClassVar[str] = "my_tool"
    
    @classmethod
    def create(cls, conv_state=None):
        return [cls(
            description="What your tool does",
            action_type=MyAction,
            observation_type=MyObservation,
            executor=MyExecutor()
        )]

# Auto-register
register_tool("my_tool", MyTool)
```

### 2. Package It

Create package structure:

```bash
my_tool_pkg/
├── setup.py
├── my_tool/
│   ├── __init__.py
│   └── tool.py  # Your tool code
```

`setup.py`:

```python
from setuptools import setup, find_packages

setup(
    name="my-custom-tool",
    version="0.1.0",
    packages=find_packages(),
)
```

### 3. Install in Sandbox

```python
# Via bash command
bash_cmd = """
mkdir -p /workspace/my_tool_pkg/my_tool
cat > /workspace/my_tool_pkg/setup.py << 'EOF'
<setup.py content>
EOF
cat > /workspace/my_tool_pkg/my_tool/tool.py << 'EOF'
<tool code>
EOF
cd /workspace/my_tool_pkg && pip install -e .
"""

requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": bash_cmd}
)
```

### 4. Use in Conversation

```python
payload = {
    "agent": {
        "tools": [{"name": "my_tool"}]
    },
    "tool_module_qualnames": {
        "my_tool": "my_tool.tool"
    }
}

requests.post(
    f"{agent_server}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json=payload
)
```

---

## Files in This Example

- **`custom_tool_definition.py`** - Rubber Duck Debugger tool definition
- **`working_example.py`** - Complete working demonstration
- **`test_tool_install.py`** - Minimal test script
- **`README.md`** - This documentation

---

## Troubleshooting

### "ModuleNotFoundError" when creating conversation

**Problem:** Agent-server can't import your module

**Solutions:**
1. Verify package was installed: `pip list | grep your-package`
2. Test import manually: `python3 -c 'import your_module'`
3. Check package structure (setup.py, __init__.py)
4. Ensure module path in `tool_module_qualnames` is correct

### "Context window too small" error

**Problem:** LLM model doesn't have sufficient context

**Solution:** Use a model with larger context window:
```python
"llm": {"model": "gpt-4o"}  # Has 128k context
```

### Tool not being called by agent

**Problem:** Agent might not understand when to use it

**Solutions:**
1. Improve tool description in `ToolDefinition.create()`
2. Be explicit in your message: "Use the X tool to do Y"
3. Check agent's available tools in response

---

## Related Examples

- **`custom-agent-no-browser`** - Configure which built-in tools agent has
- **SDK Example:** `software-agent-sdk/examples/02_remote_agent_server/06_custom_tool/`  
  (Shows custom tools with DockerDevWorkspace for local agent-server)

---

## References

- [OpenHands SDK Documentation](https://docs.openhands.dev/sdk)
- [Custom Tools Guide](https://docs.openhands.dev/sdk/guides/custom-tools)
- [Tool Registry Source](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-sdk/openhands/sdk/tool/registry.py)
- [Agent-Server Tool Loading](https://github.com/OpenHands/software-agent-sdk/blob/main/openhands-agent-server/openhands/agent_server/conversation_service.py#L723)

---

## Key Takeaways

### ✅ What We Learned

1. **`tool_module_qualnames` is designed for dynamic tool loading** - It's not a workaround, it's the intended mechanism
2. **Custom tools must be importable** - Install as Python packages via `pip`
3. **This works in Cloud!** - You can add custom server-side tools to Cloud sandboxes
4. **Package installation is the key** - Makes modules importable by agent-server

### 🎯 The Pattern

```
Define Tool → Package It → Install in Sandbox → Use via tool_module_qualnames
```

This is the **correct, working approach** for custom server-side tools in OpenHands Cloud!
