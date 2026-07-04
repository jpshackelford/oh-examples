# Tool Verification Enhancements

This document explains the enhancements made to programmatically verify agent tools.

## What Was Added

### 1. `get_available_tools()` Function

Retrieves the actual tools that were configured for the agent by fetching the `SystemPromptEvent`:

```python
def get_available_tools(agent_server_url: str, session_key: str, conv_id: str) -> list[dict]:
    """Get the list of tools that were available to the agent."""
    response = agent_server_request(
        "GET",
        agent_server_url,
        session_key,
        f"/api/conversations/{conv_id}/events/search?kind__eq=SystemPromptEvent&limit=1",
    )
    
    system_event = response.json()["items"][0]
    return system_event.get("tools", [])
```

**Key insight:** This shows which tools were *available* to the agent, not just which ones were *used*.

### 2. `display_tools()` Function

Displays tools in a grouped, concise format:

```python
def display_tools(tools: list[dict], show_descriptions: bool = False) -> None:
    """Display tools in a concise, grouped format."""
    # Groups tools by category (browser, core, MCP providers)
    # Shows count per category
    # Optional descriptions for detailed view
```

**Output example:**

```
  total tools: 7

  🔧 Core tools (5):
    • terminal
    • file_editor
    • task_tracker
    • finish
    • think

  🔌 Create tools (1):
    • default_create_pr

  🔌 Tavily tools (1):
    • default_tavily_tavily_search
```

### 3. `check_browser_tools()` Function

Programmatically verifies that browser tools are NOT in the available tools list:

```python
def check_browser_tools(tools: list[dict]) -> bool:
    """Check if browser tools are present in the tools list."""
    for tool in tools:
        title = tool.get("title", "")
        kind = tool.get("kind", "")
        
        if "browser" in title.lower() or "browser" in kind.lower():
            return True
    
    return False
```

### 4. Enhanced `verify_tools()` Function

Now performs two-stage verification:

1. **Available tools check** (from SystemPromptEvent)
   - Shows which tools were configured
   - Verifies browser tools are excluded
   
2. **Used tools check** (from ActionEvents)
   - Shows which tools were actually invoked
   - Confirms browser tools were not used

## Tool Data Structure

Each tool in the `SystemPromptEvent.tools` array has this structure:

```json
{
  "title": "terminal",
  "kind": "TerminalTool",
  "description": "Execute a shell command in the terminal...",
  "action_type": "TerminalAction",
  "observation_type": "TerminalObservation",
  "annotations": {
    "title": "terminal",
    "readOnlyHint": false,
    "destructiveHint": true,
    "idempotentHint": false,
    "openWorldHint": true
  }
}
```

## Understanding `title` vs `kind`

### `title` (Tool Name)
- Simple string identifier
- Used in tool configuration: `{"name": "terminal"}`
- Used in ActionEvents: `"tool_name": "terminal"`
- **Examples:**
  - `"terminal"`
  - `"file_editor"`
  - `"browser_navigate"`
  - `"browser_click"`
  - `"default_create_pr"`

### `kind` (Tool Class)
- Class/type name from the tool system
- Indicates the tool's implementation class
- **Examples:**
  - `"TerminalTool"`
  - `"FileEditorTool"`
  - `"BrowserNavigateTool"`
  - `"BrowserClickTool"`
  - `"MCPToolDefinition"` (for MCP tools)

### Relationship: **Not 1:1**

Multiple tools can share the same `kind`:

```
title: "default_create_pr"           -> kind: "MCPToolDefinition"
title: "default_create_mr"           -> kind: "MCPToolDefinition"
title: "default_tavily_tavily_search" -> kind: "MCPToolDefinition"
```

All MCP (Model Context Protocol) tools have `kind: "MCPToolDefinition"` but different titles.

### Grouping Strategy

The `display_tools()` function groups by **title prefix**:

1. **Browser tools:** `title.startswith("browser_")`
   - `browser_navigate`, `browser_click`, `browser_get_state`, etc.
   
2. **MCP tools:** `title.startswith("default_")`
   - Further grouped by provider: `default_<provider>_<action>`
   - Example: `default_tavily_*` → "Tavily tools" group
   
3. **Core tools:** Everything else
   - `terminal`, `file_editor`, `task_tracker`, `finish`, `think`, etc.

**Why not group by `kind`?**
- `kind` is too coarse (all MCP tools are "MCPToolDefinition")
- `title` prefix provides better semantic grouping
- Browser tools all start with `browser_` which is intuitive

## Testing

Use `test_tool_display.py` to see the output format:

```bash
python test_tool_display.py
```

This shows:
- Tool grouping behavior
- Browser detection
- Output with/without descriptions

## API Reference

### Cloud API
```
GET https://app.all-hands.dev/api/v1/conversation/{conversation_id}/events/search
  ?kind__eq=SystemPromptEvent
  &limit=1
```

**Auth:** `Authorization: Bearer $OH_API_KEY`

### Agent-Server API
```
GET {agent_server_url}/api/conversations/{conv_id}/events/search
  ?kind__eq=SystemPromptEvent
  &limit=1
```

**Auth:** `X-Session-API-Key: {session_key}`

Both return the same event structure with the `tools` array.

## Benefits

1. **Verification before execution:** Check if tools were configured correctly
2. **Clear output:** Grouped display makes it easy to spot browser tools
3. **Programmatic checks:** Can be used in automated tests
4. **Two-stage validation:** Verifies both configuration and actual usage

## Example Use Cases

### 1. Verify Configuration
```python
tools = get_available_tools(agent_server_url, session_key, conv_id)
if check_browser_tools(tools):
    print("ERROR: Browser tools are present!")
    sys.exit(1)
```

### 2. Generate Tool Report
```python
tools = get_available_tools(agent_server_url, session_key, conv_id)
display_tools(tools, show_descriptions=True)
```

### 3. Compare Configured vs Used
```python
available = {t["title"] for t in get_available_tools(...)}
used = get_tools_used_from_action_events(...)

unused = available - used
print(f"Configured but not used: {unused}")
```
