# Custom Agent With Custom Tool

Create a custom agent that includes your own tool implementation. This example adds a whimsical "Rubber Duck Debugger" tool — inspired by the classic debugging technique where you explain code problems to an inanimate object.

## Why create custom tools?

Built-in tools cover common operations (terminal, file editing, web browsing), but your agent might need specialized capabilities:

- 🛠️ **Domain-specific operations**: Call your company's internal APIs
- 🔧 **Specialized workflows**: Multi-step operations as a single tool
- 🎨 **Custom integrations**: Connect to services without built-in support
- 🧪 **Experimental features**: Test new capabilities before they're built-in

## The Rubber Duck Tool

Our custom tool implements "[rubber duck debugging](https://en.wikipedia.org/wiki/Rubber_duck_debugging)" — a real technique where programmers debug by explaining code out loud to an inanimate object. The tool:

- Accepts code snippets or problem descriptions
- Provides debugging prompts and questions
- Encourages thinking through assumptions
- Responds with appropriately duck-themed wisdom 🦆

## How custom tools work

Custom tools in the OpenHands SDK follow a structured pattern with several components:

```python
from collections.abc import Sequence
from pydantic import Field
from openhands.sdk import Action, Observation, Tool
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool

# 1. Define the Action (input schema)
class RubberDuckAction(Action):
    code: str | None = Field(default=None, description="Code to debug")
    problem: str | None = Field(default=None, description="Problem description")

# 2. Define the Observation (output schema)
class RubberDuckObservation(Observation):
    advice: str = Field(description="The duck's wisdom")

# 3. Implement the Executor (the actual logic)
class RubberDuckExecutor(ToolExecutor[RubberDuckAction, RubberDuckObservation]):
    def __call__(self, action: RubberDuckAction, conversation=None):
        advice = "🦆 *Quack!* Have you checked for off-by-one errors?"
        return RubberDuckObservation.from_text(text=advice, advice=advice)

# 4. Create the ToolDefinition (wires it all together)
class RubberDuckTool(ToolDefinition[RubberDuckAction, RubberDuckObservation]):
    @classmethod
    def create(cls, conv_state) -> Sequence["RubberDuckTool"]:
        return [cls(
            description="Rubber duck debugging wisdom",
            action_type=RubberDuckAction,
            observation_type=RubberDuckObservation,
            executor=RubberDuckExecutor(),
        )]

# 5. Register the tool so it can be referenced by name
register_tool("rubber_duck", RubberDuckTool)
```

Then use it in your agent:

```python
from openhands.sdk import Agent, Tool, LLM, Conversation
from openhands.tools.terminal import TerminalTool
from openhands.tools.file_editor import FileEditorTool

agent = Agent(
    llm=llm,
    tools=[
        Tool(name=TerminalTool.name),
        Tool(name=FileEditorTool.name),
        Tool(name="rubber_duck"),  # ← Your custom tool!
    ]
)
```

That's it! The agent can now use your tool.

## Run it (SDK Mode)

This example uses the **OpenHands SDK directly** (not the Cloud API) because custom tool code must be available in the agent's Python environment.

```bash
# Install SDK and tools
pip install openhands-sdk openhands-tools

# Set your LLM credentials
export LLM_API_KEY=your-api-key-here
export LLM_MODEL=gpt-4  # or anthropic/claude-3-5-sonnet-20241022, etc.

# Run the example
python agent_with_custom_tool.py
```

Sample output:

```
=== Custom Agent with Rubber Duck Debugger ===

Using model: anthropic/claude-3-5-sonnet-20241022

Creating agent with tools:
  ✓ terminal
  ✓ file_editor
  🦆 rubber_duck (custom!)

Workspace: /tmp/rubber-duck-demo

=== Task ===
Create a Python script called 'buggy_calculator.py' that has a function
to calculate the average of a list of numbers. Intentionally introduce
a subtle bug. Then use the rubber duck tool to help debug it.

============================================================
[Agent creates buggy code...]
[Agent invokes: rubber_duck tool with the buggy code...]
[Duck responds with debugging wisdom...]
[Agent fixes the bug based on duck's advice...]
============================================================

=== Conversation Complete ===

The agent:
  1. ✓ Created buggy code
  2. 🦆 Used the Rubber Duck tool to debug
  3. ✓ Fixed the bug!

Check /tmp/rubber-duck-demo/buggy_calculator.py for the result
```

## SDK vs Cloud: Where can you use custom tools?

| Approach | Custom Tools? | Use Case |
|----------|---------------|----------|
| **SDK (this example)** | ✅ Yes | Local development, scripts, automation |
| **Cloud API** | ⚠️ Requires packaging | Production deployments |
| **Automation system** | ✅ Yes (via upload) | Scheduled/event-triggered tasks |

### For Cloud deployments

To use custom tools with OpenHands Cloud (`app.all-hands.dev`), you need to package your tool code:

**Option 1: Custom base image** (recommended for persistent tools)

Build a Docker image with your tool pre-installed, deploy it as an agent-server, and point Cloud conversations to it. See the SDK documentation on [custom agent server images](https://docs.openhands.dev/sdk/guides/agent-server/docker-sandbox).

**Option 2: Plugin system**

Package your tool as a plugin and load it via the `plugins` parameter when creating conversations. See [`load-plugin`](../load-plugin/) example.

## Custom tool best practices

### 1. Clear descriptions

The LLM sees your tool's `description` and uses it to decide when to call the tool:

```python
description = (
    "Explain code or a problem to the Rubber Duck for debugging clarity. "
    "Use when stuck on a bug or need to think through logic. "
    "Parameters: 'code' (snippet to debug) or 'problem' (description)."
)
```

Be specific about:
- What the tool does
- When to use it
- What parameters it accepts

### 2. Type-safe parameters

Use Pydantic `Field` to document parameters:

```python
class MyAction(Action):
    query: str = Field(description="The search query")
    limit: int = Field(default=10, description="Max results to return")
```

### 3. Informative output

Return structured, readable output via `Observation.from_text()`:

```python
return RubberDuckObservation.from_text(
    text=(
        "🦆 *Quack!* Here's what I notice:\n"
        "  • Check for off-by-one errors\n"
        "  • Are variables initialized?\n"
    ),
    advice="Check for off-by-one errors and initialization"
)
```

The agent will see this output and can act on it.

## Real-world custom tool ideas

Beyond rubber ducks, here are practical custom tools:

**API Client Tool**
```python
class SlackTool(ToolDefinition):
    # Send messages to Slack channels
    ...
```

**Database Query Tool**
```python
class QueryTool(ToolDefinition):
    # Execute read-only SQL queries
    ...
```

**Deployment Tool**
```python
class DeployTool(ToolDefinition):
    # Trigger deployment pipeline
    ...
```

The possibilities are endless! 🚀

## Key takeaway

Custom tools extend what your agent can do. The SDK provides a structured pattern:

1. ✅ Define `Action` (input), `Observation` (output), and `Executor` (logic)
2. ✅ Create a `ToolDefinition` with a `create()` classmethod
3. ✅ Register with `register_tool(name, ToolClass)`
4. ✅ Add `Tool(name=...)` to your agent's tools list

For local development, it's this simple. For Cloud deployments, you'll need to package your tool code in a custom image or plugin.

## See also

- [`custom-agent-no-browser/`](../custom-agent-no-browser/) — Customize agent by selecting built-in tools
- [`load-plugin/`](../load-plugin/) — Load plugins that bundle tools and capabilities
- [OpenHands SDK Custom Tools guide](https://docs.openhands.dev/sdk/guides/custom-tools)
- [Official SDK custom tools example](https://github.com/OpenHands/software-agent-sdk/blob/main/examples/01_standalone_sdk/02_custom_tools.py)
