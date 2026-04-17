# Per-Conversation Secrets via REST API

This example demonstrates how to inject per-conversation secrets into an OpenHands conversation
using only REST APIs (no WebSocket required).

## Overview

OpenHands allows users to define secrets at the user level, but sometimes you need to pass
secrets that are specific to a single conversation - for example, a temporary API token or
a session-specific credential.

**This has been proven to work!** The test script successfully:
1. Starts a sandbox via the App Server API
2. Starts a conversation with that sandbox
3. Injects secrets via the Agent Server API
4. Verifies the secrets are available as environment variables

## Architecture

```
┌─────────────────────┐     ┌─────────────────────┐     ┌─────────────────────┐
│   App Server        │     │   Agent Server      │     │   MCP Server        │
│ app.all-hands.dev   │     │ (per-sandbox URL)   │     │ (validates token)   │
├─────────────────────┤     ├─────────────────────┤     ├─────────────────────┤
│ POST /v1/sandboxes  │────▶│                     │     │                     │
│ POST /v1/app-conv   │     │                     │     │                     │
│                     │     │ POST /secrets       │────▶│ validate_token()    │
│                     │     │ POST /events        │     │                     │
└─────────────────────┘     └─────────────────────┘     └─────────────────────┘
        │                           │                           │
        │   Authorization:          │   X-Session-API-Key:      │   Authorization:
        │   Bearer {api_key}        │   {session_api_key}       │   Bearer ${SECRET}
```

## Key Findings

1. **Two Different Conversation IDs**: The App Server and Agent Server use different IDs
   for the same conversation. You must query the Agent Server to find the correct ID.

2. **Two Authentication Schemes**:
   - App Server: `Authorization: Bearer {api_key}`
   - Agent Server: `X-Session-API-Key: {session_api_key}`

3. **Secrets Endpoint**: `POST /api/conversations/{id}/secrets`
   - Body: `{"secrets": {"KEY": "value"}}`
   - Secrets become environment variables (`$KEY`)

4. **MCP Config Variable Expansion**: MCP server configurations support `${VARIABLE}`
   syntax that expands using injected secrets.

## Files

- `test_secrets.py` - End-to-end test proving secrets work as environment variables
- `mcp_server.py` - Simple MCP server for testing token validation
- `test_mcp_secrets.py` - (Experimental) Test for MCP config variable expansion

## Usage

```bash
# Set your API key
export OH_API_KEY="sk-oh-..."

# Run the basic test (proven to work)
python test_secrets.py

# Expected output:
# ======================================================================
#   PER-CONVERSATION SECRETS TEST
# ======================================================================
# [HH:MM:SS] Starting sandbox...
# [HH:MM:SS]   Sandbox ID: ...
# [HH:MM:SS] Waiting for sandbox to be ready...
# [HH:MM:SS]   Agent Server: https://xxxx.prod-runtime.all-hands.dev
# [HH:MM:SS] Starting conversation...
# [HH:MM:SS]   Conversation ID: ...
# [HH:MM:SS] Injecting secret: TEST_SECRET_TOKEN=FUZZY_WUZZY...
# [HH:MM:SS]   Result: {'success': True}
# ...
# ======================================================================
#   ✅ SUCCESS! Per-conversation secret was injected and used!
# ======================================================================
```

## API Workflow

```python
# 1. Start sandbox
POST https://app.all-hands.dev/api/v1/sandboxes
Headers: Authorization: Bearer {api_key}
→ {id, session_api_key, exposed_urls}

# 2. Wait for RUNNING status, get agent_server_url from exposed_urls

# 3. Start conversation
POST https://app.all-hands.dev/api/v1/app-conversations
Headers: Authorization: Bearer {api_key}
Body: {sandbox_id: "...", initial_message: {...}}

# 4. Find conversation on agent server
GET {agent_server_url}/api/conversations/search
Headers: X-Session-API-Key: {session_api_key}

# 5. Inject secrets
POST {agent_server_url}/api/conversations/{agent_conv_id}/secrets
Headers: X-Session-API-Key: {session_api_key}
Body: {"secrets": {"MY_SECRET": "value"}}
→ {"success": true}

# 6. Secret is now available as $MY_SECRET in the conversation!
```

## License

MIT License - see [LICENSE](../LICENSE) for details.
