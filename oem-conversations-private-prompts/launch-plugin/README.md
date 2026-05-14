# Launch Plugin

Plugin for the customer-facing conversation.

## Purpose

This plugin:
- Exposes MCP tools for requesting travel guides
- Handles customer interaction and preference gathering
- Communicates with the MCP server to trigger private conversations
- Monitors for results and presents them to the customer

## Key Features

- **No Proprietary Content**: This plugin contains NO secret prompts or techniques
- **MCP Integration**: Calls the MCP server with customer credentials
- **Async Handling**: Can check for results while engaging the customer

## Tools Exposed

- `request_travel_guide(destination, preferences)` - Start guide generation
- `check_guide_status(request_id)` - Check if guide is ready
- `get_guide_link(request_id)` - Get link to generated guide

## Configuration

Requires environment variables:
- `MCP_SERVER_URL` - URL of the MCP server
- `MCP_AUTH_TOKEN` - Authentication token for MCP calls
