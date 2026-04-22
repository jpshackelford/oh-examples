# Per-Conversation Secrets via REST API

This example demonstrates how to inject per-conversation secrets into an OpenHands conversation
using only REST APIs (no WebSocket required).

## Overview

OpenHands allows users to define secrets at the user level, but sometimes you need to pass
secrets that are specific to a single conversation - for example, a temporary API token or
a session-specific credential.

## APIs Used

These tests exercise **two separate OpenHands APIs**:

### 1. App Server API
- **Purpose**: Manages sandboxes, conversations, and user resources
- **Base URL**: `https://app.all-hands.dev/api` (or custom deployment)
- **Auth Header**: `X-Access-Token: <your_api_key>`
- **OpenAPI Spec**: `https://app.all-hands.dev/openapi.json`

### 2. Agent Server API
- **Purpose**: Direct agent interaction within a running sandbox
- **Base URL**: Obtained from sandbox's `exposed_urls` array (look for `name="AGENT_SERVER"`)
- **Auth Header**: `X-Session-API-Key: <session_api_key>` (from sandbox creation response)
- **OpenAPI Spec**: `{agent_server_url}/openapi.json`

> **Tip**: To explore the Agent Server API, first create a sandbox via the App Server,
> wait for it to reach RUNNING status, then fetch `{agent_server_url}/openapi.json`.

## Two Approaches

There are now **two ways** to inject per-conversation secrets:

### 1. At Conversation Start (NEW - Recommended)

Pass secrets directly in the `POST /v1/app-conversations` request body:

```python
requests.post(
    f'{api_url}/v1/app-conversations',
    headers={'X-Access-Token': api_key},  # App Server auth
    json={
        'sandbox_id': sandbox_id,
        'initial_message': {...},
        'secrets': {                    # <-- New field!
            'GITHUB_TOKEN': 'ghp_...',
            'MY_API_KEY': 'sk-...',
        }
    }
)
```

**Advantages:**
- Single request - simpler API
- Secrets available immediately when agent starts
- No race condition - guaranteed to be set before agent runs
- Secrets are merged with vault secrets (API secrets take precedence)

**Requirements:**
- OpenHands PR [#14009](https://github.com/OpenHands/OpenHands/pull/14009)
- SDK PR [#2873](https://github.com/OpenHands/software-agent-sdk/pull/2873)

**Test script:** `test_secrets_at_start.py`

### 2. After Conversation Start (Original)

Inject secrets via the Agent Server's `/secrets` endpoint after the conversation starts:

```python
# After starting conversation...
requests.post(
    f'{agent_server_url}/api/conversations/{conv_id}/secrets',
    headers={'X-Session-API-Key': session_api_key},
    json={'secrets': {'MY_SECRET': 'value'}}
)
```

**Use when:**
- Need to add secrets mid-conversation
- Running on older OpenHands versions

**Test script:** `test_secrets.py`

## Quick Comparison

| Feature | At Start (New) | After Start (Original) |
|---------|----------------|------------------------|
| API | App Server | Agent Server |
| Endpoint | `POST /v1/app-conversations` | `POST /api/conversations/{id}/secrets` |
| Auth Header | `X-Access-Token: {api_key}` | `X-Session-API-Key: {session_key}` |
| Timing | Before agent runs | After conversation created |
| Simplicity | Single request | Multiple requests |
| Mid-conversation | No | Yes |

## Proven to Work!

Both approaches have been tested and verified:

**At-start approach (`test_secrets_at_start.py`):**
1. Starts a sandbox via the App Server API
2. Starts a conversation with secrets in the request body
3. Verifies the secrets are available as environment variables

**After-start approach (`test_secrets.py`):**
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
   - App Server: `X-Access-Token: {api_key}`
   - Agent Server: `X-Session-API-Key: {session_api_key}`

3. **Secrets Endpoint** (Agent Server): `POST /api/conversations/{id}/secrets`
   - Body: `{"secrets": {"KEY": "value"}}`
   - Secrets become environment variables (`$KEY`) for **bash commands**

4. **MCP Config Variable Expansion - LIMITATION**:
   - MCP configs support `${VARIABLE}` syntax
   - BUT: This expands from `os.environ`, NOT from injected secrets
   - Injected secrets go to `SecretRegistry` (used for bash commands)
   - Therefore: Per-conversation secrets do NOT work for MCP config expansion
   - **Workaround**: Use user-level secrets (defined in OpenHands settings) for MCP authentication

## Files

- `test_secrets_at_start.py` - **NEW**: Test secrets passed at conversation start (recommended)
- `test_secrets.py` - Test secrets injected after conversation start (original approach)
- `mcp_server.py` - Simple MCP server for testing token validation
- `test_mcp_secrets.py` - (Experimental) Test for MCP config variable expansion

## Usage

### Test secrets at conversation start (NEW - Recommended)

```bash
# Set your API key
export OH_API_KEY="sk-oh-..."

# Optional: Use a staging or feature deployment for testing
# export OH_API_URL="https://ohpr-14009-30.staging.all-hands.dev/api"

# Optional: Use an existing running sandbox (faster, avoids cold start issues)
# export OH_SANDBOX_ID="your-sandbox-id"

# Run the test
python test_secrets_at_start.py

# Expected output:
# ======================================================================
#  PER-CONVERSATION SECRETS AT START TIME TEST
#  Testing: secrets field in AppConversationStartRequest
# ======================================================================
#
# [HH:MM:SS] Using API URL: https://app.all-hands.dev/api
# [HH:MM:SS] Starting sandbox...
# [HH:MM:SS]   Sandbox ID: ...
# [HH:MM:SS] Waiting for sandbox to be ready...
# [HH:MM:SS]   Status: STARTING
# [HH:MM:SS]   Status: RUNNING
# [HH:MM:SS]   Agent Server: https://xxxx.prod-runtime.all-hands.dev
# [HH:MM:SS] Starting conversation with secrets field...
# [HH:MM:SS]   Secret: TEST_API_SECRET='FUZZY_WUZZY_WAS_A_BE...'
# [HH:MM:SS]   Response status: 200
# ...
# ======================================================================
#  ✅ SUCCESS! Secrets field was accepted in AppConversationStartRequest!
# ======================================================================
```

### Test secrets after conversation start (Original)

```bash
# Set your API key
export OH_API_KEY="sk-oh-..."

# Run the test
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
# ============================================================
# APP SERVER API (https://app.all-hands.dev/api)
# Auth: X-Access-Token header
# ============================================================

# 1. Create sandbox
POST /v1/sandboxes
Headers: X-Access-Token: {api_key}
→ {id, session_api_key, status: "STARTING", exposed_urls: null}

# 2. Poll for RUNNING status
GET /v1/sandboxes/search
Headers: X-Access-Token: {api_key}
→ {items: [{id, status: "RUNNING", exposed_urls: [...], session_api_key}]}
# Find AGENT_SERVER in exposed_urls array

# 3. Start conversation WITH secrets (new approach)
POST /v1/app-conversations
Headers: X-Access-Token: {api_key}
Body: {sandbox_id: "...", initial_message: {...}, secrets: {...}}

# ============================================================
# AGENT SERVER API (from exposed_urls AGENT_SERVER)
# Auth: X-Session-API-Key header
# ============================================================

# 4. Find conversation on agent server
GET /api/conversations/search
Headers: X-Session-API-Key: {session_api_key}
→ {items: [{id, status}]}

# 5. Send message / check events
POST /api/conversations/{id}/events
GET /api/conversations/{id}/events/search
Headers: X-Session-API-Key: {session_api_key}
```

## API Reference

### App Server API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/v1/sandboxes` | POST | Create sandbox → `{id, session_api_key, ...}` |
| `/v1/sandboxes/search` | GET | List sandboxes → `{items: [...]}` |
| `/v1/sandboxes/{id}` | DELETE | Delete sandbox (use `?sandbox_id=` query param) |
| `/v1/app-conversations` | POST | Start conversation (supports `secrets` field) |

### Agent Server API

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/conversations/search` | GET | List conversations → `{items: [...]}` |
| `/api/conversations/{id}/secrets` | POST | Inject secrets → `{success: true}` |
| `/api/conversations/{id}/events` | POST | Send user message |
| `/api/conversations/{id}/events/search` | GET | List events → `{items: [...]}` |

### Getting the OpenAPI Specs

```bash
# App Server OpenAPI
curl https://app.all-hands.dev/openapi.json

# Agent Server OpenAPI (requires running sandbox)
# 1. Create sandbox and wait for RUNNING status
# 2. Get agent_server_url from exposed_urls (name="AGENT_SERVER")
curl {agent_server_url}/openapi.json
```

## License

MIT License - see [LICENSE](../LICENSE) for details.
