# Secret Token Validator

This plugin provides access to a token validation MCP server.

## Tools

- `validate_token` - Validates that the secret token was correctly passed via MCP config variable expansion

## Usage

The MCP server expects a token via the `Authorization: Bearer ${MCP_SECRET_TOKEN}` header.
The `${MCP_SECRET_TOKEN}` variable is expanded from the conversation's injected secrets.
