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

# Test secret - use a distinctive value we can verify
SECRET_NAME = 'TEST_API_SECRET'
SECRET_VALUE = 'FUZZY_WUZZY_WAS_A_BEAR_FUZZY_WUZZY_HAD_NO_HAIR'


def log(msg: str) -> None:
    """Print with timestamp."""
    print(f'[{time.strftime("%H:%M:%S")}] {msg}')


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

    # Step 1: Start sandbox
    log('Starting sandbox...')
    resp = requests.post(f'{API_URL}/v1/sandboxes', headers=headers, json={}, timeout=60)
    if resp.status_code != 200:
        log(f'Error starting sandbox: {resp.status_code}')
        log(resp.text)
        return 1

    sandbox = resp.json()
    sandbox_id = sandbox['sandbox_id']
    log(f'  Sandbox ID: {sandbox_id}')

    # Step 2: Wait for sandbox to be ready
    log('Waiting for sandbox to be ready...')
    agent_url = None
    for _ in range(60):
        resp = requests.get(f'{API_URL}/v1/sandboxes/{sandbox_id}', headers=headers, timeout=30)
        if resp.status_code == 200:
            data = resp.json()
            agent_url = data.get('agent_server_url')
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

    # Wait for conversation to be created and get ID
    time.sleep(3)
    conversation_id = conv_data.get('id')
    if not conversation_id:
        # Poll for conversation
        for _ in range(10):
            resp = requests.get(
                f'{API_URL}/v1/conversations', headers=headers, params={'sandbox_id': sandbox_id}
            )
            if resp.status_code == 200:
                convs = resp.json()
                if convs:
                    conversation_id = convs[0].get('id')
                    break
            time.sleep(2)

    log(f'  Conversation ID: {conversation_id}')

    # Step 4: Wait for initial message to complete
    log('Waiting for initial message to complete...')
    time.sleep(15)

    # Step 5: Send a message that uses the secret
    log(f'Sending message: Run this exact command: echo ${SECRET_NAME} | tr \'[:upper:]...')
    resp = requests.post(
        f'{API_URL}/v1/conversations/{conversation_id}/messages',
        headers=headers,
        json={
            'role': 'user',
            'content': [
                {
                    'type': 'text',
                    'text': f"Run this exact command: echo ${SECRET_NAME} | tr '[:upper:]' '[:lower:]'",
                }
            ],
        },
        timeout=60,
    )

    # Step 6: Wait and check for the secret in output
    log('Waiting for agent to execute command...')
    time.sleep(45)

    log('Checking events for transformed secret...')
    resp = requests.get(
        f'{API_URL}/v1/conversations/{conversation_id}/events', headers=headers, timeout=30
    )

    if resp.status_code == 200:
        events = resp.json()
        log(f'  Total events: {len(events)}')

        # Look for our secret value (transformed to lowercase)
        expected_lower = SECRET_VALUE.lower()
        for event in events:
            obs = event.get('observation', {})
            content = obs.get('content', '')
            if expected_lower in content.lower():
                log('  Found secret in output!')
                print()
                print('=' * 70)
                print(f' ✅ SUCCESS! Secrets passed at conversation start time work!')
                print(f'    Secret: {SECRET_NAME}={SECRET_VALUE}')
                print('    The secret was passed via the new \'secrets\' field in')
                print('    AppConversationStartRequest and was available as an')
                print('    environment variable to the agent.')
                print('=' * 70)
                cleanup(headers, sandbox_id)
                return 0

        log('  Secret not found in output. Events:')
        for event in events[-5:]:
            log(f'    {event.get("observation_type", event.get("action_type", "?"))}: {str(event)[:100]}...')

    print()
    print('=' * 70)
    print(' ❌ FAILED: Could not verify secret was available')
    print('=' * 70)
    cleanup(headers, sandbox_id)
    return 1


def cleanup(headers: dict, sandbox_id: str) -> None:
    """Clean up sandbox."""
    log('Cleaning up sandbox...')
    try:
        requests.delete(f'{API_URL}/v1/sandboxes/{sandbox_id}', headers=headers, timeout=30)
    except Exception:
        pass
    log('  Done.')


if __name__ == '__main__':
    sys.exit(main())
