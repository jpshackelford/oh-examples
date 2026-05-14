# MCP Server

The secure proxy layer that connects customer conversations to private processing.

## Purpose

This MCP server:
- Authenticates incoming requests with token-based auth
- Validates customer ID and customer secret
- Starts private OpenHands conversations with proprietary plugins
- Tracks conversation state in SQLite
- Returns results to the customer-facing conversation

## Architecture

```
Customer Conversation ──► MCP Server ──► Private Conversation
        │                     │                    │
        │                     │                    │
        ▼                     ▼                    ▼
   launch-plugin          SQLite DB        proprietary-plugin
                                                   │
                                                   ▼
                                           Shared Sandbox
                                          (HTML/CSS/Assets)
```

## Endpoints

### MCP Tool Endpoints
- `POST /tools/generate_travel_guide` - Start guide generation
- `GET /tools/check_status/{request_id}` - Check processing status
- `GET /tools/get_result/{request_id}` - Get result details

### Admin Endpoints
- `GET /admin/conversations` - List all conversations (admin auth required)
- `GET /health` - Health check

## Authentication

1. **MCP Auth Token**: Bearer token for all MCP calls
2. **Customer Credentials**: `customer_id` + `customer_secret` validated per request

## Database Schema

```sql
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    public_conversation_id TEXT NOT NULL,
    private_conversation_id TEXT,
    status TEXT DEFAULT 'pending',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP,
    result_path TEXT
);

CREATE TABLE customers (
    customer_id TEXT PRIMARY KEY,
    customer_secret_hash TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

## Running

```bash
uv sync
uv run uvicorn server:app --host 0.0.0.0 --port 8080
```

## Environment Variables

- `OPENHANDS_API_KEY` - For starting private conversations
- `MCP_AUTH_TOKEN` - Token for authenticating MCP calls
- `DATABASE_PATH` - Path to SQLite database (default: `./mcp_state.db`)
