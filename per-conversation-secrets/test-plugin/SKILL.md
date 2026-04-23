# Secret Token Validator

This plugin provides access to a token validation MCP server.

## Tools

- `validate_token` - Validates that the secret token was correctly passed via MCP config variable expansion

## Required Secrets

This plugin requires two secrets to be injected at conversation start:

- `MCP_SERVER_URL` - The base URL of the MCP server (e.g., `https://work-1-xxx.prod-runtime.all-hands.dev`)
- `MCP_SECRET_TOKEN` - The secret token that the MCP server expects

## Usage

The MCP config uses variable expansion for both the server URL and the authorization token:
- Server URL: `${MCP_SERVER_URL}/mcp`  
- Auth header: `Authorization: Bearer ${MCP_SECRET_TOKEN}`

Both variables are expanded from the conversation's injected secrets (passed via the `secrets` field in `AppConversationStartRequest`).
