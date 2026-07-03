# Custom Agent With Custom Tool

Create a custom agent that includes your own tool implementation. This example adds a whimsical "Rubber Duck Debugger" tool — inspired by the classic debugging technique where you explain code problems to an inanimate object.

## Why create custom tools?

Built-in tools cover common operations (bash, file editing, web browsing), but your agent might need specialized capabilities:

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

Custom tools are Python classes that inherit from `ToolDefinition`:

```python
from openhands.sdk.tool import ToolDefinition

class RubberDuckTool(ToolDefinition):
    name = "rubber_duck"
    description = "Explain code to the Rubber Duck for debugging clarity."
    
    def execute(self, code: str | None = None, **kwargs) -> str:
        # Tool implementation here
        return "🦆 *Quack!* Here's what I notice..."
```

Then register it with your agent:

```python
from openhands.sdk import Agent, Tool

agent = Agent(
    llm=llm,
    tools=[
        Tool(name="bash"),
        Tool(name="file_editor"),
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
  ✓ bash
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
| **Cloud API** | ⚠️ Requires upload | Production deployments |
| **Automation system** | ✅ Yes (via tarball) | Scheduled/event-triggered tasks |

### For Cloud deployments

To use custom tools with OpenHands Cloud (`app.all-hands.dev`), you have three options:

**Option 1: Automation system** (recommended for scheduled/event-driven tasks)

Package your tool and agent as a tarball and upload via the automation API:

```python
# Structure:
my-automation/
  ├── main.py                 # Entrypoint
  ├── tools/
  │   └── rubber_duck.py      # Your tool
  └── requirements.txt

# Upload as tarball to /api/automation/v1/preset/...
```

See [automation documentation](https://github.com/OpenHands/OpenHands/tree/main/automation) for details.

**Option 2: Custom base image**

Build a Docker image with your tool pre-installed, deploy it as an agent-server, and point Cloud conversations to it.

**Option 3: Plugin system**

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

### 2. Error handling

Raise `ToolError` for invalid inputs:

```python
from openhands.sdk.tool import ToolError

def execute(self, code: str | None = None, **kwargs) -> str:
    if not code:
        raise ToolError("Please provide 'code' parameter!")
    # ...
```

### 3. Informative output

Return structured, readable output:

```python
return (
    "🦆 *Quack!* Here's what I notice:\n"
    "  • Check for off-by-one errors\n"
    "  • Are variables initialized?\n"
    "  • Try printing intermediate values\n"
)
```

The agent will see this output and can act on it.

## Real-world custom tool ideas

Beyond rubber ducks, here are practical custom tools:

**API Client Tool**
```python
class SlackTool(ToolDefinition):
    name = "slack"
    description = "Send messages to Slack channels"
    
    def execute(self, channel: str, message: str) -> str:
        # Call Slack API
        ...
```

**Database Query Tool**
```python
class QueryTool(ToolDefinition):
    name = "query_db"
    description = "Execute read-only SQL queries"
    
    def execute(self, query: str) -> str:
        # Execute query, return results
        ...
```

**Deployment Tool**
```python
class DeployTool(ToolDefinition):
    name = "deploy"
    description = "Deploy code to staging environment"
    
    def execute(self, branch: str) -> str:
        # Trigger deployment pipeline
        ...
```

The possibilities are endless! 🚀

## Key takeaway

Custom tools extend what your agent can do. The SDK makes it trivial:

1. ✅ Define a class with `name`, `description`, and `execute()`
2. ✅ Add `Tool(name="your_tool")` to the agent's tools list
3. ✅ The agent can now use your tool!

For local development, it's this simple. For Cloud deployments, you'll need to package and upload your tool code.

## Files in this example

- `agent_with_custom_tool.py` — Complete working example with RubberDuckTool
- `README.md` — This file

## See also

- [`custom-agent-no-browser/`](../custom-agent-no-browser/) — Customize agent by selecting built-in tools
- [`load-plugin/`](../load-plugin/) — Load plugins that bundle tools and capabilities
- [OpenHands SDK Tool documentation](https://docs.openhands.dev/sdk/guides/custom-tools)
- [OpenHands SDK Custom Tools guide](https://docs.openhands.dev/sdk/guides/custom-tools)
