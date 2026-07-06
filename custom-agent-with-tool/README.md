# custom-agent-with-tool

Add a **completely custom, server-side tool** to an OpenHands Cloud agent — without
forking or rebuilding the agent-server. The agent-server loads your tool at
conversation-creation time via the `tool_module_qualnames` mechanism.

The example ships a small demo tool (the Rubber Duck Debugger) and proves, end to
end, that the agent **registers** and **uses** it.

## The core idea: declare + locate

Creating a conversation with a custom tool is a two-part contract:

- `agent.tools` — **which** tools to activate, by name:
  `[{"name": "terminal"}, {"name": "file_editor"}, {"name": "rubber_duck"}]`
- `tool_module_qualnames` — **where** a tool comes from, as an importable module:
  `{"rubber_duck": "rubber_duck.tool"}`

On conversation creation the agent-server imports each mapped module. Importing has
a **side effect**: the module's `register_tool("rubber_duck", RubberDuckTool)` call
runs and registers the tool. If the name is requested but nothing registered it,
the server returns `ToolDefinition '<name>' is not registered`.

Built-in tools (`terminal`, `file_editor`, ...) don't need an entry — the server
already knows where those live. **Only your custom tools need a qualname mapping.**

## Prerequisites

```bash
pip install requests
export OH_API_KEY=your-openhands-cloud-api-key
export LLM_API_KEY=your-llm-api-key
```

Optional overrides (sensible defaults are used otherwise):

```bash
export LLM_MODEL=litellm_proxy/claude-sonnet-4-5-20250929
export LLM_BASE_URL=https://llm-proxy.app.all-hands.dev/
```

## Run it

```bash
python working_example.py            # runs and cleans up the sandbox
python working_example.py --keep     # leave the sandbox up for inspection
```

Expected output:

```
[demo] === Verification ===
[demo]   registered tools: ['terminal', 'file_editor', 'rubber_duck', 'finish', 'think']
[demo]   tools used: ['rubber_duck']
[demo]   PASS: custom tool 'rubber_duck' is registered
[demo]   PASS: custom tool 'rubber_duck' was used by the agent
[demo] SUCCESS: the custom tool was loaded and used in OpenHands Cloud.
```

## How it works

1. **Create a sandbox** (`POST /api/v1/sandboxes`) and wait for `RUNNING`. Read the
   `AGENT_SERVER` URL and the `session_api_key` from the sandbox record.
2. **Deploy the tool** as an importable package in the conversation's working
   directory, `/workspace/rubber_duck/`, using the agent-server file API
   (`POST /api/file/upload?path=...`). Two files are uploaded: `__init__.py` and
   `tool.py` (the contents of `custom_tool_definition.py`).
3. **Create a conversation** (`POST /api/conversations`) that lists the tool in
   `agent.tools` and maps it in `tool_module_qualnames`.
4. **Run and verify** (`POST .../run`, then read events). The custom tool must show
   up in the `SystemPromptEvent.tools` list (registered) and as an `ActionEvent`
   `tool_name` (used).

### Why upload into the working directory (and not `pip install`)?

On OpenHands Cloud the agent-server is a **frozen, self-contained binary** (built
with PyInstaller). A normal `pip install` targets a *different* Python interpreter
that the frozen server cannot see, so the module would never be importable and the
tool would fail to register.

The conversation's **working directory is on the agent-server's import path**, so
dropping the package there makes `import rubber_duck.tool` work with no install
step. The tool's own imports (`openhands.sdk`, `pydantic`) resolve from inside the
frozen server, where they're always available.

Uploading the file (rather than writing it through a shell heredoc) also means the
**tool source can contain anything** — quotes, `EOF` markers, backslashes — with no
escaping or injection pitfalls.

## Verifying registration (same technique as `custom-agent-no-browser`)

The agent-server records a `SystemPromptEvent` whose `tools` array is the exact set
of tools the agent was given. Both examples read it the same way:

```python
system_events = [e for e in items if e.get("kind") == "SystemPromptEvent"]
registered = [t.get("title") for t in system_events[0].get("tools", [])]
assert "rubber_duck" in registered          # registered / available
assert "rubber_duck" in tools_used          # actually invoked (from ActionEvents)
```

## The example tool

`custom_tool_definition.py` defines a `rubber_duck` tool with the OpenHands SDK: a
`ToolDefinition` + typed `Action`/`Observation` + an `Executor`. It takes a `problem`
(and optional `code`) and returns rubber-duck debugging advice. Importing the module
registers the tool.

The prompt in `working_example.py` is **directive** — it explicitly says *"Use the
rubber_duck tool"* — so the happy path is deterministic on every run. That proves the
tool is registered, callable, and returns output. It does not test whether the agent
would *discover* the tool unprompted from its description; for that, use a non-leading
prompt and let the model choose.

## Files

| File | Purpose |
|------|---------|
| `working_example.py` | End-to-end runner: create sandbox -> deploy tool -> run -> verify -> clean up |
| `custom_tool_definition.py` | The custom tool, implemented with the OpenHands SDK (uploaded as `tool.py`) |

## Cleanup

Without `--keep` the sandbox is deleted automatically. With `--keep`, delete it when
done:

```bash
curl -X DELETE "https://app.all-hands.dev/api/v1/sandboxes/<id>?sandbox_id=<id>" \
  -H "Authorization: Bearer $OH_API_KEY"
```

> Note: `DELETE /api/v1/sandboxes/{id}` requires `sandbox_id` as **both** the path
> segment and a query parameter; omitting the query parameter returns HTTP 422 and
> leaks the sandbox.
