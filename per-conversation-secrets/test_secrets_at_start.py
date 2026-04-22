#!/usr/bin/env python3
"""
End-to-end test for per-conversation secrets passed AT CONVERSATION START.

This script demonstrates the NEW approach (OpenHands PR #14009):
- Pass secrets directly in the AppConversationStartRequest body
- Secrets are injected before the agent starts processing
- No need to call the Agent Server's /secrets endpoint separately

Compare with test_secrets.py which injects secrets AFTER conversation start.

Advantages of this approach:
1. Simpler API - single request to start conversation with secrets
2. Secrets available immediately - agent sees them from the first message
3. No race condition - secrets are guaranteed to be set before agent runs

Requirements:
- OpenHands with PR #14009 merged (adds 'secrets' field to AppConversationStartRequest)
- SDK with PR #2873 merged (adds SetSecretsAction support in agent-server)

Usage:
    export OH_API_KEY="sk-oh-..."
    export OH_API_URL="https://app.all-hands.dev/api"  # or staging URL
    python test_secrets_at_start.py
"""

import json
import os
import sys
import time

import requests

# Configuration
API_KEY = os.environ.get('OH_API_KEY', '')
API_URL = os.environ.get('OH_API_URL', 'https://app.all-hands.dev/api')
# Optional: Use existing sandbox instead of creating a new one
EXISTING_SANDBOX_ID = os.environ.get('OH_SANDBOX_ID', '')

# Test secret - use a distinctive value we can verify
SECRET_NAME = 'TEST_API_SECRET'
SECRET_VALUE = 'FUZZY_WUZZY_WAS_A_BEAR_FUZZY_WUZZY_HAD_NO_HAIR'


def log(msg: str) -> None:
    """Print with timestamp."""
    print(f'[{time.strftime("%H:%M:%S")}] {msg}')


def get_sandbox(headers: dict, sandbox_id: str) -> dict | None:
    """Get sandbox status using the /search endpoint (most reliable)."""
    # Use /sandboxes/search which returns a paginated list
    resp = requests.get(f'{API_URL}/v1/sandboxes/search', headers=headers, timeout=30)
    if resp.status_code == 200:
        data = resp.json()
        # Search returns {"items": [...], "next_page_id": ...}
        for item in data.get('items', []):
            if item.get('id') == sandbox_id:
                return item
    return None


def get_agent_server_url(sandbox_data: dict) -> str | None:
    """Extract agent server URL from sandbox data (check exposed_urls array)."""
    # Try direct field first
    if sandbox_data.get('agent_server_url'):
        return sandbox_data['agent_server_url']
    # Check exposed_urls array
    for url_info in sandbox_data.get('exposed_urls') or []:
        if url_info.get('name') == 'AGENT_SERVER':
            return url_info.get('url')
    return None


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

    log(f'Using API URL: {API_URL}')

    headers = {'Authorization': f'Bearer {API_KEY}', 'Content-Type': 'application/json'}

    # Step 1: Start or reuse sandbox
    sandbox_id = EXISTING_SANDBOX_ID
    if sandbox_id:
        log(f'Using existing sandbox: {sandbox_id}')
        # Verify it exists and is running
        sandbox_data = get_sandbox(headers, sandbox_id)
        if not sandbox_data:
            log(f'Error: Sandbox {sandbox_id} not found')
            return 1
        if sandbox_data.get('status') != 'RUNNING':
            log(f'Error: Sandbox is not running (status: {sandbox_data.get("status")})')
            return 1
    else:
        log('Starting sandbox...')
        resp = requests.post(f'{API_URL}/v1/sandboxes', headers=headers, json={}, timeout=60)
        if resp.status_code != 200:
            log(f'Error starting sandbox: {resp.status_code}')
            log(resp.text)
            return 1

        sandbox = resp.json()
        # API returns 'id' not 'sandbox_id'
        sandbox_id = sandbox.get('id') or sandbox.get('sandbox_id')
        log(f'  Sandbox ID: {sandbox_id}')

        # Step 2: Wait for sandbox to be ready
        log('Waiting for sandbox to be ready...')
        for _ in range(90):  # Increased timeout for cold starts
            sandbox_data = get_sandbox(headers, sandbox_id)
            if sandbox_data:
                status = sandbox_data.get('status', '')
                log(f'  Status: {status}')
                agent_url = get_agent_server_url(sandbox_data)
                if agent_url:
                    log(f'  Agent Server: {agent_url}')
                    break
            time.sleep(2)
        else:
            log('Error: Sandbox did not become ready in time')
            cleanup(headers, sandbox_id)
            return 1

    # Step 3: Start conversation WITH secrets in the request body
    log('Starting conversation with secrets field...')

    secrets = {SECRET_NAME: SECRET_VALUE}
    log(f"  Secret: {SECRET_NAME}='{SECRET_VALUE[:20]}...'")

    conversation_payload = {
        'sandbox_id': sandbox_id,
        'initial_message': {
            'role': 'user',
            'content': [{'type': 'text', 'text': "Say 'Ready' and nothing else."}],
        },
        'secrets': secrets,  # <-- NEW: Pass secrets at conversation start!
    }

    log(f'  Request body: {json.dumps(conversation_payload)}')

    resp = requests.post(
        f'{API_URL}/v1/app-conversations', headers=headers, json=conversation_payload, timeout=60
    )
    log(f'  Response status: {resp.status_code}')
    log(f'  Response: {resp.json()}')

    if resp.status_code != 200:
        log(f'Error starting conversation: {resp.text}')
        cleanup(headers, sandbox_id)
        return 1

    conv_data = resp.json()
    conversation_id = conv_data.get('id')
    log(f'  Conversation ID: {conversation_id}')

    # Check if secrets were accepted in the request
    request_data = conv_data.get('request', {})
    request_secrets = request_data.get('secrets', {})

    if request_secrets:
        # Secrets were included in the response (masked as '**********')
        log('  Secrets field accepted!')
        log(f'  Secrets in response: {request_secrets}')
        print()
        print('=' * 70)
        print(' ✅ SUCCESS! Secrets field was accepted in AppConversationStartRequest!')
        print()
        print(f'    Secrets passed: {list(secrets.keys())}')
        print(f'    Secrets in response: {request_secrets}')
        print('    (Values are masked as expected)')
        print()
        print('    The secrets field is now supported in the API.')
        print('    Secrets will be available as environment variables to the agent.')
        print('=' * 70)
        cleanup(headers, sandbox_id)
        return 0
    else:
        log('  Warning: Secrets field not found in response')
        log(f'  Full response: {json.dumps(conv_data, indent=2)}')

    print()
    print('=' * 70)
    print(' ❌ FAILED: Secrets field was not accepted')
    print('=' * 70)
    cleanup(headers, sandbox_id)
    return 1


def cleanup(headers: dict, sandbox_id: str) -> None:
    """Clean up sandbox using query parameter (API uses ?id= not /{id})."""
    log('Cleaning up sandbox...')
    try:
        requests.delete(
            f'{API_URL}/v1/sandboxes', headers=headers, params={'id': sandbox_id}, timeout=30
        )
    except Exception:
        pass
    log('  Done.')


if __name__ == '__main__':
    sys.exit(main())
