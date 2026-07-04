# Custom Tool Creation with OpenHands SDK

This example demonstrates how to create a custom tool that extends the agent's capabilities beyond the built-in tools (terminal, file_editor, browser, etc.).

## What This Example Shows

✅ **How to define a custom tool** using Action/Observation/Executor pattern  
✅ **How to register and use the tool** in an agent  
✅ **Complete working example** (Rubber Duck Debugger)  
✅ **How to deploy to Cloud** (via automation pattern)  

## Key Insight: Custom Tools Require Code

**You CANNOT add custom tools via API calls alone.**

Unlike tool *selection* (which can be configured via `PATCH /api/settings`), custom tools require:

1. **Python code** that defines the tool's behavior
2. **SDK imports** (`Action`, `Observation`, `Executor`, `ToolDefinition`)
3. **Registration** via `register_tool()`
4. **Inclusion** in the Agent's tools list

This code must run **inside the agent's execution environment**.

## Two Deployment Patterns

### Pattern 1: Local SDK Execution (This Example)

Run the agent with custom tools locally using the SDK:

```bash
pip install openhands-sdk openhands-tools
export LLM_API_KEY=your-api-key
export LLM_MODEL=gpt-4
python agent_with_custom_tool.py
```

**Pros:**
- Simple and direct
- Full control over execution
- Easy to test and debug

**Cons:**
- Runs on your local machine (no Cloud sandbox)
- No persistent workspace
- No Cloud UI integration

### Pattern 2: Cloud Deployment via Automation (Production)

Package the code as a tarball and upload via automation API:

**Step 1: Create main.py with custom tool**
```python
# main.py - same as agent_with_custom_tool.py
from openhands.sdk import Agent, Conversation, Tool
from openhands.sdk.tool import register_tool

# ... define RubberDuckAction, Observation, Executor, Tool ...
register_tool("rubber_duck", RubberDuckTool)

# Create agent with custom tool
agent = Agent(llm=llm, tools=[
    Tool(name="terminal"),
    Tool(name="file_editor"),
    Tool(name="rubber_duck"),  # Custom!
])

conversation = Conversation(agent=agent, workspace=workspace)
conversation.send_message(task)
conversation.run()
```

**Step 2: Create setup.sh**
```bash
#!/bin/bash
python3 -m venv .venv
.venv/bin/pip install openhands-sdk openhands-tools
```

**Step 3: Package as tarball**
```bash
tar -czf custom-agent.tar.gz main.py setup.sh
```

**Step 4: Upload via automation API**

This example doesn't implement the full automation upload (that's complex), but the pattern from `OpenHands/automation` is:

```python
import requests

# Upload tarball to Cloud storage
response = requests.post(
    "https://app.all-hands.dev/api/automation/v1/uploads",
    headers={"Authorization": f"Bearer {api_key}"},
    files={"file": open("custom-agent.tar.gz", "rb")}
)
upload_id = response.json()["id"]

# Create automation that references the tarball
requests.post(
    "https://app.all-hands.dev/api/automation/v1",
    headers={"Authorization": f"Bearer {api_key}"},
    json={
        "name": "Custom Tool Agent",
        "tarball_path": f"internal://{upload_id}",
        "entrypoint": ".venv/bin/python main.py",
        "setup_script_path": "setup.sh",
        "trigger": {"type": "manual"}
    }
)
```

See `../AGENT_CUSTOMIZATION_FINDINGS.md` for details on the automation pattern.

## How Custom Tools Work

### The Five Required Components

Every custom tool needs these five pieces:

#### 1. Action (Input)

Defines what parameters the agent provides:

```python
class RubberDuckAction(Action):
    code: str | None = Field(default=None)
    problem: str = Field(...)
```

#### 2. Observation (Output)

Defines what the tool returns to the agent:

```python
class RubberDuckObservation(Observation):
    advice: str = Field(...)
```

#### 3. Executor (Logic)

Implements the actual tool behavior:

```python
class RubberDuckExecutor(ToolExecutor[RubberDuckAction, RubberDuckObservation]):
    def __call__(self, action, conversation=None):
        # Do the work
        advice = generate_advice(action.problem, action.code)
        return RubberDuckObservation.from_text(text=advice, advice=advice)
```

#### 4. ToolDefinition (Wiring)

Connects Action, Observation, and Executor:

```python
class RubberDuckTool(ToolDefinition[RubberDuckAction, RubberDuckObservation]):
    @classmethod
    def create(cls, conv_state=None):
        return [cls(
            description="A rubber duck debugging assistant...",
            action_type=RubberDuckAction,
            observation_type=RubberDuckObservation,
            executor=RubberDuckExecutor(),
        )]
```

#### 5. Registration

Makes the tool available by name:

```python
register_tool("rubber_duck", RubberDuckTool)
```

### Using the Custom Tool

Once registered, include it in the agent's tools:

```python
agent = Agent(
    llm=llm,
    tools=[
        Tool(name="terminal"),
        Tool(name="file_editor"),
        Tool(name="rubber_duck"),  # Your custom tool!
    ]
)
```

The agent can now use `rubber_duck` just like any built-in tool.

## Usage

### Prerequisites

```bash
# Install SDK
pip install openhands-sdk openhands-tools

# Set LLM credentials
export LLM_API_KEY=your-api-key
export LLM_MODEL=gpt-4  # or anthropic/claude-3-5-sonnet-20241022

# Optional: custom base URL
export LLM_BASE_URL=https://api.your-llm-provider.com
```

### Run the Example

```bash
python agent_with_custom_tool.py
```

Expected output:

```
============================================================
Custom Agent with Rubber Duck Debugger
============================================================

Using model: gpt-4

Creating agent with tools:
  ✓ terminal
  ✓ file_editor
  🦆 rubber_duck (custom!)

Workspace: /tmp/rubber-duck-demo

============================================================
Task
============================================================
Create a Python script called 'buggy_calculator.py' that has a function
to calculate the average of a list of numbers. Intentionally introduce
a subtle bug...
============================================================

[Agent conversation happens...]

============================================================
Conversation Complete
============================================================

The agent:
  1. ✓ Created buggy code
  2. 🦆 Used the Rubber Duck tool to debug
  3. ✓ Fixed the bug!

Check /tmp/rubber-duck-demo/buggy_calculator.py for the result

The key point: The agent had access to our custom 'rubber_duck' tool
and used it just like any built-in tool! 🦆
```

### Customize the Workspace

```bash
export WORKSPACE_DIR=/path/to/your/workspace
python agent_with_custom_tool.py
```

## The Rubber Duck Tool

This example implements a "Rubber Duck Debugger" - a tool that helps debug code by providing systematic debugging suggestions.

**Why a rubber duck?**

From Wikipedia: "Rubber duck debugging is a method of debugging code by articulating a problem in spoken or written natural language. The name is a reference to a story in the book *The Pragmatic Programmer* in which a programmer would carry around a rubber duck and debug their code by forcing themselves to explain it, line-by-line, to the duck."

**What it does:**
- Accepts a code snippet and problem description
- Returns debugging suggestions and advice
- Demonstrates how custom tools can extend agent capabilities

**Example usage by the agent:**
```python
# Agent calls the tool like this:
rubber_duck(
    code="def average(nums): return sum(nums) / (len(nums) - 1)",
    problem="This average function returns wrong results"
)

# Tool returns:
🦆 *Quack!* Let's debug this together!

Problem: This average function returns wrong results

Code provided:
```
def average(nums): return sum(nums) / (len(nums) - 1)
```

Debugging suggestions:
1. Check your assumptions - print intermediate values
2. Verify inputs - are they what you expect?
3. Test edge cases - empty lists, None values, etc.
...
```

## Real-World Custom Tool Examples

Custom tools can do anything you can code. Here are real-world examples:

### API Integration Tool

```python
class APICallAction(Action):
    endpoint: str
    method: str = "GET"
    data: dict | None = None

class APICallExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        response = requests.request(
            method=action.method,
            url=f"https://api.example.com/{action.endpoint}",
            json=action.data
        )
        return APICallObservation.from_text(
            text=response.text,
            status_code=response.status_code,
            data=response.json()
        )
```

### Database Query Tool

```python
class DatabaseQueryAction(Action):
    query: str

class DatabaseQueryExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        conn = sqlite3.connect("app.db")
        cursor = conn.execute(action.query)
        results = cursor.fetchall()
        return DatabaseQueryObservation.from_text(
            text=str(results),
            rows=results
        )
```

### Code Analysis Tool

```python
class CodeAnalysisAction(Action):
    file_path: str
    analysis_type: str  # "complexity", "coverage", "style"

class CodeAnalysisExecutor(ToolExecutor):
    def __call__(self, action, conversation=None):
        if action.analysis_type == "complexity":
            result = analyze_complexity(action.file_path)
        elif action.analysis_type == "style":
            result = run_pylint(action.file_path)
        return CodeAnalysisObservation.from_text(
            text=result,
            issues=result.issues
        )
```

## Comparison: Built-in vs Custom Tools

| Aspect | Built-in Tools | Custom Tools |
|--------|---------------|--------------|
| **Availability** | Always available | Must be registered |
| **Configuration** | Via `agent_settings.tools` API | Requires Python code |
| **Deployment** | Pre-installed in agent-server | Must upload code/tarball |
| **Examples** | terminal, file_editor, browser | Any code you write |
| **Use Cases** | General purpose | Domain-specific needs |

## Why Can't I Just Configure Custom Tools?

You might wonder: "Why can't I just do `PATCH /api/settings` with a custom tool name?"

**Because the agent-server doesn't know what your tool does.**

Built-in tools like `terminal` have their code already present in the agent-server:
- `TerminalTool` class exists
- Executor knows how to run bash commands
- Action/Observation schemas are defined

Your custom tool's code doesn't exist in the agent-server until you:
1. Upload it (via tarball)
2. Run it (which calls `register_tool()`)
3. Include it in the agent

**This is why you need the automation pattern for Cloud deployment.**

## Deployment Architecture

### Local SDK Pattern

```
┌──────────────────────────────────────┐
│  Your Machine                        │
│                                      │
│  1. Define custom tool (Python)      │
│  2. Register tool (register_tool)    │
│  3. Create agent (Agent(tools=[...]))│
│  4. Run conversation                 │
└──────────────────────────────────────┘
```

### Cloud Automation Pattern

```
┌──────────────────────────────────────┐
│  Your Machine                        │
│  1. Package: main.py + setup.sh      │
│  2. Tarball: custom-agent.tar.gz     │
│  3. Upload via automation API        │
└──────────────────────────────────────┘
           │
           │ uploads to
           ▼
┌──────────────────────────────────────┐
│  Cloud Storage                       │
│  - Stores tarball                    │
│  - Returns upload_id                 │
└──────────────────────────────────────┘
           │
           │ referenced by
           ▼
┌──────────────────────────────────────┐
│  Automation Service                  │
│  - Tracks tarball_path               │
│  - Triggers runs                     │
└──────────────────────────────────────┘
           │
           │ dispatches to
           ▼
┌──────────────────────────────────────┐
│  Agent-Server (Sandbox)              │
│  1. Download tarball                 │
│  2. Run setup.sh                     │
│  3. Execute main.py                  │
│     - Defines custom tool            │
│     - Registers tool                 │
│     - Creates agent                  │
│     - Runs conversation              │
└──────────────────────────────────────┘
```

## Next Steps

- See `../custom-agent-no-browser/` for tool **selection** (not creation)
- See [OpenHands SDK Custom Tools Guide](https://docs.openhands.dev/sdk/guides/custom-tools)
- See official SDK examples: `software-agent-sdk/examples/01_standalone_sdk/02_custom_tools.py`
- See `../AGENT_CUSTOMIZATION_FINDINGS.md` for automation upload patterns

## Troubleshooting

### "No module named 'openhands'"

Install the SDK:
```bash
pip install openhands-sdk openhands-tools
```

### "LLM_API_KEY environment variable not set"

Set your LLM credentials:
```bash
export LLM_API_KEY=your-api-key
export LLM_MODEL=gpt-4
```

### Tool not being used by agent

Check:
1. Tool is registered: `register_tool("my_tool", MyTool)`
2. Tool is in agent's tools list: `Tool(name="my_tool")`
3. Tool name matches exactly (case-sensitive)
4. Tool description is clear and helpful

### Want to deploy to Cloud?

The full automation pattern is complex. For now:
1. Use this example to test your custom tool locally
2. When ready for production, study `OpenHands/automation/presets/`
3. Or contact OpenHands support for deployment assistance

## Related Examples

- **custom-agent-no-browser**: Configure tool *selection* via agent-server API
- **automation examples** (OpenHands/automation repo): Full production deployment patterns
