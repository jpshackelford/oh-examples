# oh-examples

A collection of example code for working with the OpenHands API.

## Examples

| Example | Description |
|---------|-------------|
| [conversation-metrics](./conversation-metrics/) | CLI tool to retrieve cost and token usage for conversations |
| [per-conversation-secrets](./per-conversation-secrets/) | Inject per-conversation secrets via REST API — both as bash env vars and to template an **MCP server** config (`.mcp.json`) bundled in a plugin |
| [start-sandbox](./start-sandbox/) | Start a sandbox (no conversation) and run commands via the agent-server REST API |
| [clone-and-attach](./clone-and-attach/) | Clone a repo + run `.openhands/setup.sh` in a sandbox, then attach a conversation to it |
| [upload-skills](./upload-skills/) | Upload a local agent-skills directory into a sandbox, then start a conversation that uses them |
| [load-plugin](./load-plugin/) | Minimal: start a conversation with a plugin pre-loaded via the REST API |
| [launch-plugin-badge](./launch-plugin-badge/) | Build a no-code `/launch` link, HTML button, or README badge that loads a plugin |

## API Versions

OpenHands has two API versions:

- **V0 API** (Legacy) - Deprecated since v1.0.0, scheduled for removal April 1, 2026
- **V1 API** - Current recommended API

These examples aim to support both API versions where possible, with graceful fallback behavior.

## Getting Started

Each example has its own README with installation and usage instructions.

### Authentication

Most examples require an OpenHands API key. Set it as an environment variable:

```bash
export OH_API_KEY="your-api-key"
```

Or pass it via command-line argument (see individual example documentation).

## Related Resources

- [OpenHands Documentation](https://docs.all-hands.dev/)
- [OpenHands API Reference](https://app.all-hands.dev/docs)
- [oh-websocket-example](https://github.com/jpshackelford/oh-websocket-example) - V0 WebSocket API example

## License

MIT License - see [LICENSE](LICENSE) for details.
