#!/usr/bin/env python3
"""
End-to-end test for per-conversation secrets passed AT CONVERSATION START.

## Overview

This script tests the NEW approach for injecting secrets (OpenHands PR #14009):
- Pass secrets directly in the AppConversationStartRequest body
- Secrets are injected before the agent starts processing
- No need to call the Agent Server's /secrets endpoint separately

Compare with test_secrets.py which injects secrets AFTER conversation start.

## APIs Used

This test exercises TWO separate OpenHands APIs:

1. **App Server API** - Manages sandboxes and conversations
   - Base URL: https://app.all-hands.dev/api (or OH_API_URL)
   - Auth: `X-Access-Token: <api_key>` header
   - OpenAPI spec: `{base_url}/openapi.json`
   - Used for: Creating sandboxes, starting conversations with secrets

2. **Agent Server API** - Direct agent interaction within a sandbox
   - Base URL: Obtained from sandbox's `exposed_urls` (name="AGENT_SERVER")
   - Auth: `X-Session-API-Key: <session_api_key>` header
   - OpenAPI spec: `{agent_server_url}/openapi.json`
   - Used for: Sending messages, retrieving events, verifying secrets work

## Requirements

- OpenHands with PR #14009 merged (adds 'secrets' field to AppConversationStartRequest)
- SDK with PR #2873 merged (adds SetSecretsAction support in agent-server)

## Usage

    export OH_API_KEY="sk-oh-..."
    export OH_API_URL="https://app.all-hands.dev/api"  # optional, defaults to prod
    export OH_SANDBOX_ID="existing-sandbox-id"         # optional, reuse sandbox
    python test_secrets_at_start.py
"""

import json
import os
import sys
import time
from typing import Any

import requests

# Configuration
API_KEY = os.environ.get('OH_API_KEY', '')
API_URL = os.environ.get('OH_API_URL', 'https://app.all-hands.dev/api')
EXISTING_SANDBOX_ID = os.environ.get('OH_SANDBOX_ID', '')

# Test secret - use a distinctive value we can verify in output
SECRET_NAME = 'TEST_API_SECRET'
SECRET_VALUE = 'FUZZY_WUZZY_WAS_A_BEAR_FUZZY_WUZZY_HAD_NO_HAIR'


def log(msg: str) -> None:
    """Print with timestamp."""
    print(f'[{time.strftime("%H:%M:%S")}] {msg}')


# =============================================================================
# App Server API Functions (sandbox and conversation management)
# =============================================================================


def get_sandbox_via_search(headers: dict, sandbox_id: str) -> dict | None:
    """
    Get sandbox by ID using GET /v1/sandboxes/search.

    Per OpenAPI: Returns paginated list with {items: [...], next_page_id: ...}
    """
    resp = requests.get(f'{API_URL}/v1/sandboxes/search', headers=headers, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        for item in data.get('items', []):
            if item.get('id') == sandbox_id:
                return item
    return None


def create_sandbox(headers: dict) -> dict:
    """
    Create a new sandbox via POST /v1/sandboxes.

    Per OpenAPI: Returns SandboxInfo with {id, status, session_api_key, exposed_urls, ...}
    """
    resp = requests.post(f'{API_URL}/v1/sandboxes', headers=headers, json={}, timeout=60)
    resp.raise_for_status()
    return resp.json()


def delete_sandbox(headers: dict, sandbox_id: str) -> None:
    """
    Delete sandbox via DELETE /v1/sandboxes/{id}?sandbox_id=<id>.

    Per OpenAPI: Path is /v1/sandboxes/{id} with sandbox_id as query parameter.
    Note: The {id} in path is literal, sandbox_id is passed as query param.
    """
    try:
        requests.delete(
            f'{API_URL}/v1/sandboxes/{{id}}',
            headers=headers,
            params={'sandbox_id': sandbox_id},
            timeout=30,
        )
    except Exception:
        pass


def start_conversation_with_secrets(
    headers: dict, sandbox_id: str, secrets: dict[str, str], initial_message: str
) -> dict:
    """
    Start conversation with secrets via POST /v1/app-conversations.

    Per OpenAPI: AppConversationStartRequest accepts 'secrets' field.
    Returns AppConversationStartTask with {id, status, request, ...}
    """
    payload = {
        'sandbox_id': sandbox_id,
        'initial_message': {
            'role': 'user',
            'content': [{'type': 'text', 'text': initial_message}],
        },
        'secrets': secrets,
    }
    resp = requests.post(
        f'{API_URL}/v1/app-conversations', headers=headers, json=payload, timeout=60
    )
    resp.raise_for_status()
    return resp.json()


# =============================================================================
# Agent Server API Functions (direct agent interaction)
# =============================================================================


def get_agent_server_info(sandbox_data: dict) -> tuple[str, str] | None:
    """
    Extract agent server URL and session key from sandbox data.

    Per OpenAPI: SandboxInfo has exposed_urls array with {name, url, port}.
    Look for name="AGENT_SERVER" to get the agent server URL.
    """
    session_key = sandbox_data.get('session_api_key')
    if not session_key:
        return None

    for url_info in sandbox_data.get('exposed_urls') or []:
        if url_info.get('name') == 'AGENT_SERVER':
            return url_info.get('url'), session_key
    return None


def get_agent_conversations(agent_url: str, session_key: str) -> list[dict]:
    """
    List conversations via GET /api/conversations/search.

    Per Agent Server OpenAPI: Returns {items: [...], next_page_id: ...}
    Auth: X-Session-API-Key header
    """
    headers = {'X-Session-API-Key': session_key}
    resp = requests.get(f'{agent_url}/api/conversations/search', headers=headers, timeout=30)
    resp.raise_for_status()
    return resp.json().get('items', [])


def send_user_message(agent_url: str, session_key: str, conv_id: str, message: str) -> bool:
    """
    Send user message via POST /api/conversations/{id}/events.

    Per Agent Server OpenAPI: Accepts message with role, content, and run flag.
    Auth: X-Session-API-Key header
    """
    headers = {'X-Session-API-Key': session_key, 'Content-Type': 'application/json'}
    payload = {
        'role': 'user',
        'content': [{'type': 'text', 'text': message}],
        'run': True,
    }
    resp = requests.post(
        f'{agent_url}/api/conversations/{conv_id}/events',
        headers=headers,
        json=payload,
        timeout=60,
    )
    return resp.status_code == 200


def get_conversation_events(agent_url: str, session_key: str, conv_id: str) -> list[dict]:
    """
    Get events via GET /api/conversations/{id}/events/search.

    Per Agent Server OpenAPI: Returns {items: [...], next_page_id: ...}
    Auth: X-Session-API-Key header
    """
    headers = {'X-Session-API-Key': session_key}
    resp = requests.get(
        f'{agent_url}/api/conversations/{conv_id}/events/search',
        headers=headers,
        params={'limit': 100},
        timeout=60,
    )
    if resp.status_code == 200:
        return resp.json().get('items', [])
    return []


def check_events_for_secret(events: list[dict], expected_value: str) -> bool:
    """Check if the secret value appears in any event output."""
    expected_lower = expected_value.lower()
    for event in events:
        obs = event.get('observation', {})
        if isinstance(obs, dict):
            content = obs.get('content', '')
            # Handle both string and list content formats
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = item.get('text', '')
                        if expected_lower in text.lower():
                            return True
            elif isinstance(content, str) and expected_lower in content.lower():
                return True
    return False


# =============================================================================
# Main Test Logic
# =============================================================================


def main() -> int:
    if not API_KEY:
        print('Error: Please set OH_API_KEY environment variable')
        print('  export OH_API_KEY="sk-oh-..."')
        return 1

    print('=' * 70)
    print(' PER-CONVERSATION SECRETS AT START TIME TEST')
    print(' Testing: secrets field in AppConversationStartRequest')
    print('=' * 70)
    print()

    log(f'App Server API: {API_URL}')
    log(f'  OpenAPI spec: {API_URL.replace("/api", "")}/openapi.json')

    app_headers = {'X-Access-Token': API_KEY, 'Content-Type': 'application/json'}
    sandbox_id = None
    agent_url = None
    session_key = None

    try:
        # Step 1: Get or create sandbox
        if EXISTING_SANDBOX_ID:
            sandbox_id = EXISTING_SANDBOX_ID
            log(f'Using existing sandbox: {sandbox_id}')
            sandbox_data = get_sandbox_via_search(app_headers, sandbox_id)
            if not sandbox_data:
                log(f'Error: Sandbox {sandbox_id} not found')
                return 1
            if sandbox_data.get('status') != 'RUNNING':
                log(f'Error: Sandbox not running (status: {sandbox_data.get("status")})')
                return 1
        else:
            log('Creating sandbox...')
            sandbox_data = create_sandbox(app_headers)
            sandbox_id = sandbox_data.get('id')
            log(f'  Sandbox ID: {sandbox_id}')

            # Wait for sandbox to be ready
            log('Waiting for sandbox to be ready...')
            for _ in range(90):
                sandbox_data = get_sandbox_via_search(app_headers, sandbox_id)
                if sandbox_data:
                    status = sandbox_data.get('status', '')
                    if status == 'RUNNING':
                        break
                    log(f'  Status: {status}')
                time.sleep(2)
            else:
                log('Error: Sandbox did not become ready in time')
                return 1

        # Get agent server info
        agent_info = get_agent_server_info(sandbox_data)
        if not agent_info:
            log('Error: Could not get agent server URL from sandbox')
            return 1
        agent_url, session_key = agent_info
        log(f'Agent Server API: {agent_url}')
        log(f'  OpenAPI spec: {agent_url}/openapi.json')

        # Get baseline conversations on agent server
        before_convs = {c['id'] for c in get_agent_conversations(agent_url, session_key)}

        # Step 2: Start conversation WITH secrets
        log('Starting conversation with secrets field...')
        secrets = {SECRET_NAME: SECRET_VALUE}
        log(f"  Secret: {SECRET_NAME}='{SECRET_VALUE[:20]}...'")

        conv_task = start_conversation_with_secrets(
            app_headers, sandbox_id, secrets, "Say 'Ready' and nothing else."
        )
        log(f'  Response status: 200')

        # Verify secrets were accepted in request
        request_secrets = conv_task.get('request', {}).get('secrets', {})
        if not request_secrets:
            log('Error: Secrets field not accepted in API response')
            return 1
        log(f'  Secrets accepted (masked): {request_secrets}')

        # Step 3: Find the new conversation on agent server
        log('Finding conversation on agent server...')
        agent_conv_id = None
        for _ in range(30):
            after_convs = {c['id'] for c in get_agent_conversations(agent_url, session_key)}
            new_convs = after_convs - before_convs
            if new_convs:
                agent_conv_id = list(new_convs)[0]
                break
            time.sleep(1)

        if not agent_conv_id:
            log('Error: Conversation did not appear on agent server')
            return 1
        log(f'  Agent conversation ID: {agent_conv_id}')

        # Step 4: Wait for initial message to complete
        log('Waiting for initial message to complete...')
        time.sleep(15)

        # Step 5: Send message that uses the secret
        log(f'Sending command to use secret: echo ${SECRET_NAME} | tr ...')
        message = f"Run this exact command: echo ${SECRET_NAME} | tr '[:upper:]' '[:lower:]'"
        if not send_user_message(agent_url, session_key, agent_conv_id, message):
            log('Error: Failed to send message')
            return 1

        # Step 6: Wait for agent to execute
        log('Waiting for agent to execute command...')
        time.sleep(45)

        # Step 7: Check events for the secret value
        log('Checking events for transformed secret...')
        events = get_conversation_events(agent_url, session_key, agent_conv_id)
        log(f'  Total events: {len(events)}')

        if check_events_for_secret(events, SECRET_VALUE):
            print()
            print('=' * 70)
            print(' ✅ SUCCESS! Secrets passed at conversation start time work!')
            print()
            print(f'    Secret: {SECRET_NAME}={SECRET_VALUE}')
            print('    The secret was passed via the new "secrets" field in')
            print('    AppConversationStartRequest and was available as an')
            print('    environment variable to the agent.')
            print('=' * 70)
            return 0
        else:
            log('  Secret not found in output')
            log('  Recent events:')
            for event in events[-5:]:
                etype = event.get('kind', '?')
                log(f'    {etype}: {str(event)[:80]}...')

        print()
        print('=' * 70)
        print(' ❌ FAILED: Could not verify secret was available to agent')
        print('=' * 70)
        return 1

    except requests.RequestException as e:
        log(f'Error: API request failed: {e}')
        return 1
    except Exception as e:
        log(f'Error: {e}')
        import traceback

        traceback.print_exc()
        return 1
    finally:
        if sandbox_id and not EXISTING_SANDBOX_ID:
            log('Cleaning up sandbox...')
            delete_sandbox(app_headers, sandbox_id)
            log('  Done.')


if __name__ == '__main__':
    sys.exit(main())
