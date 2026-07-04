# Testing Guide for Corrected Examples

This guide shows how to test the corrected custom agent examples.

## Prerequisites

- Python 3.11+
- Access to OpenHands Cloud (for custom-agent-no-browser)
- LLM API key (for custom-agent-with-tool)

## Test 1: custom-agent-no-browser (Cloud API)

This example uses only the Cloud REST API, no SDK installation needed.

### Setup:
```bash
cd custom-agent-no-browser
pip install requests
export OH_API_KEY=your-cloud-api-key  # Get from https://app.all-hands.dev
```

### Run:
```bash
python agent_no_browser.py
```

### Expected Output:
```
=== creating conversation with custom agent (no browser) ===
Task: Create a Python script called 'hello.py' that prints 'Hello, Custom Agent!' Then show me the file content to confirm it was created.

  start-task status: SETTING_UP_SKILLS
  start-task status: STARTING_CONVERSATION
  start-task status: READY
conversation: <conversation-id>
  sandbox status: RUNNING

=== waiting for agent to complete task ===
  execution status: running
  execution status: running
  execution status: finished
  ✓ agent completed the task

=== result ===
View the conversation: https://app.all-hands.dev/conversations/<conversation-id>

The agent completed the task.
To verify which tools were actually available, check the conversation UI.

=== cleanup ===
  deleted conversation <conversation-id>
  deleted sandbox <sandbox-id>
```

### Success Criteria:
- ✅ Conversation created successfully
- ✅ `execution_status` transitions from `running` to `finished`
- ✅ No timeout (should complete in ~30 seconds)
- ✅ Cleanup completes without errors

### Keep the conversation for inspection:
```bash
python agent_no_browser.py --keep
```

This will skip cleanup and show you the conversation URL to inspect in the UI.

---

## Test 2: custom-agent-with-tool (SDK)

This example requires the OpenHands SDK to be installed locally.

### Setup:
```bash
cd custom-agent-with-tool
pip install openhands-sdk openhands-tools
export LLM_API_KEY=your-llm-api-key
export LLM_MODEL=gpt-4  # or anthropic/claude-3-5-sonnet-20241022
```

### Run:
```bash
python agent_with_custom_tool.py
```

### Expected Output:
```
=== Custom Agent with Rubber Duck Debugger ===

Using model: gpt-4

Creating agent with tools:
  ✓ terminal
  ✓ file_editor
  🦆 rubber_duck (custom!)

Workspace: /tmp/rubber-duck-demo

=== Task ===
Create a Python script called 'buggy_calculator.py' that has a function
to calculate the average of a list of numbers. Intentionally introduce
a subtle bug. Then use the rubber_duck tool to help debug it.

============================================================
[Agent conversation output...]
============================================================

=== Conversation Complete ===

The agent:
  1. ✓ Created buggy code
  2. 🦆 Used the Rubber Duck tool to debug
  3. ✓ Fixed the bug!

Check /tmp/rubber-duck-demo/buggy_calculator.py for the result

The key point: The agent had access to our custom 'rubber_duck' tool
and used it just like any built-in tool! 🦆
```

### Success Criteria:
- ✅ Agent builds without errors
- ✅ Conversation runs to completion
- ✅ `rubber_duck` tool appears in agent's available tools
- ✅ Agent invokes the custom tool during execution
- ✅ Files created in `/tmp/rubber-duck-demo/`

### Verify the custom tool was used:
```bash
# Check the conversation output for rubber duck tool invocations
# Look for messages like:
# "Tool: rubber_duck"
# "🦆 *Quack!* ..."
```

---

## Troubleshooting

### custom-agent-no-browser:

**Problem**: `agent_state: UNKNOWN` for 300 seconds
- ✅ **FIXED**: This was the original bug. Now uses `execution_status` field.

**Problem**: `KeyError: 'OH_API_KEY'`
- Solution: Make sure to `export OH_API_KEY=...` before running

**Problem**: 422 error from API
- Solution: Check that your API key is valid and has permissions

### custom-agent-with-tool:

**Problem**: `ModuleNotFoundError: No module named 'openhands'`
- Solution: Run `pip install openhands-sdk openhands-tools`

**Problem**: `ToolError` import error
- ✅ **FIXED**: This was the original bug. Now uses correct imports.

**Problem**: `PydanticUserError: Field 'description' defined on a base class was overridden`
- ✅ **FIXED**: This was the original bug. Now uses proper Pydantic Field definitions.

---

## What Changed

### Before (original code):
- `custom-agent-with-tool`: ImportError on line 1, couldn't run at all
- `custom-agent-no-browser`: Never detected completion, always timeout

### After (corrected code):
- `custom-agent-with-tool`: Follows official SDK pattern, ready to run
- `custom-agent-no-browser`: Successfully completes in ~30 seconds

---

## Next Steps

If both examples work:
1. ✅ Examples are ready for merge to main
2. ✅ Can be used as templates for custom agents
3. ✅ Can be included in documentation/tutorials

If there are issues:
1. Check SDK version: `python -c "import openhands.sdk; print(openhands.sdk.__version__)"`
2. Expected version: 1.31.0 or later
3. Check Python version: `python --version` (should be 3.11+)
4. Report issues with full error traceback
