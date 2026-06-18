# Load a plugin into a conversation (minimal)

The smallest useful recipe for starting an OpenHands Cloud conversation that has
a **plugin pre-loaded**, using only the V1 App Server REST API. One field —
`plugins` — does the work.

This example is **self-contained**: it ships its own plugin in
[`dad-joke/`](./dad-joke/) and loads it straight from this repo on GitHub. No
external marketplace, no API keys beyond your OpenHands key.

> A plugin is a small git-hosted bundle of slash commands, skills, hooks, and/or
> MCP servers (Claude Code "plugin marketplace" format). `dad-joke` ships one of
> each kind we need: a `/dad-joke:about` slash command that tells a dad joke
> about an animal, and a keyword-triggered skill that asks for your favorite
> animal first.

Want a **clickable link / README badge** instead of code? See the companion
example [`launch-plugin-badge`](../launch-plugin-badge/), which builds on this
one.

## The one field that matters

```python
requests.post(
    f"{base_url}/api/v1/app-conversations",
    headers={"Authorization": f"Bearer {api_key}"},
    json={
        "plugins": [
            {
                "source": "github:jpshackelford/oh-examples",
                "ref": "main",
                "repo_path": "load-plugin/dad-joke",
            }
        ],
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": "/dad-joke:about duck"}],
        },
    },
)
```

A plugin spec has three parts:

| Field | Meaning | Example |
|-------|---------|---------|
| `source` | Where the plugin lives | `github:jpshackelford/oh-examples` |
| `ref` | Git ref/branch/tag | `main` |
| `repo_path` | Plugin sub-directory within the source | `load-plugin/dad-joke` |

> The plugin is fetched from the **`ref`** you name. While iterating on a
> branch, pass `--ref your-branch` so the fetch finds your copy; it resolves to
> `main` once merged.

## Two ways to drive it

The `initial_message` decides what happens once the plugin is loaded:

1. **Run a skill immediately via an entry command.** Send the plugin's slash
   command as the first message. The SDK registers `/dad-joke:about` as a
   keyword trigger, so this tells a joke right away:

   ```bash
   python load_plugin.py --message "/dad-joke:about duck"
   ```

2. **Load the plugin, then prompt normally.** Send a natural-language message;
   the plugin's skills are available for the agent to use when relevant. The
   bundled skill fires on "dad joke", asks for your favorite animal, then
   delivers:

   ```bash
   python load_plugin.py --message "Tell me a dad joke"
   ```

## How the call works

`POST /api/v1/app-conversations` is **asynchronous**. It returns a *start task*,
not a finished conversation. The script polls
`GET /api/v1/app-conversations/start-tasks?ids=<task_id>` until the task yields
an `app_conversation_id`, then prints the conversation URL.

(Omitting `sandbox_id` from the request lets the server provision a fresh
sandbox. To attach to a sandbox you prepared yourself, pass its id — see
[`clone-and-attach`](../clone-and-attach/).)

## Run it

```bash
pip install requests
export OH_API_KEY="sk-oh-..."     # Cloud API key

python load_plugin.py             # dad-joke + "/dad-joke:about duck"
```

### Options

| Flag | Env var | Default |
|------|---------|---------|
| `--api-key` | `OH_API_KEY` | – (required) |
| `--base-url` | `OH_API_BASE` | `https://app.all-hands.dev` |
| `--source` | `PLUGIN_SOURCE` | `github:jpshackelford/oh-examples` |
| `--ref` | `PLUGIN_REF` | `main` |
| `--repo-path` | `PLUGIN_REPO_PATH` | `load-plugin/dad-joke` |
| `--message` | `INITIAL_MESSAGE` | `/dad-joke:about duck` |
| `--poll-timeout` | `POLL_TIMEOUT` | `240` |

## The bundled plugin

```
dad-joke/
├── .claude-plugin/
│   └── plugin.json          # manifest: name, entry_command, parameters
├── commands/
│   └── about.md             # the /dad-joke:about slash command
└── skills/
    └── dad-joke/
        └── SKILL.md         # keyword skill: asks your favorite animal first
```

## Related

- [`launch-plugin-badge`](../launch-plugin-badge/) — turn this into a no-code
  launch link, HTML button, or README badge.
- [Plugins](https://docs.openhands.dev/overview/plugins) — what plugins are and
  the marketplace/plugin-directory format used here.
- [SDK Plugins guide](https://docs.openhands.dev/sdk/guides/plugins) — loading
  plugins directly from Python with the OpenHands SDK.
- [Plugin Launch Flow design doc](https://github.com/OpenHands/OpenHands/blob/main/enterprise/doc/design-doc/plugin-launch-flow.md)
  — the full marketplace → frontend → app server → SDK journey.
