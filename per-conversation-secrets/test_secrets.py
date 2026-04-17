#!/usr/bin/env python3
"""
End-to-end test for per-conversation secrets via REST API.

This script demonstrates:
1. Starting a sandbox and conversation
2. Injecting a per-conversation secret
3. Verifying the secret is available to the agent (as environment variable)

For MCP config expansion test, see test_mcp_secrets.py

Usage:
    export OH_API_KEY="sk-oh-..."
    python test_secrets.py
"""

import os
import sys
import time
import json
import requests
from typing import Any

# Configuration
API_KEY = os.environ.get('OH_API_KEY', '')
APP_URL = "https://app.all-hands.dev/api"

# Test secret
SECRET_NAME = "TEST_SECRET_TOKEN"
SECRET_VALUE = "FUZZY_WUZZY_WAS_A_BEAR_FUZZY_WUZZY_HAD_NO_HAIR"


def log(msg: str) -> None:
    """Print with timestamp."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def start_sandbox() -> dict[str, Any]:
    """Start a new sandbox and wait for it to be ready."""
    headers = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    
    log("Starting sandbox...")
    resp = requests.post(f"{APP_URL}/v1/sandboxes", headers=headers, timeout=60)
    resp.raise_for_status()
    sandbox = resp.json()
    sandbox_id = sandbox["id"]
    log(f"  Sandbox ID: {sandbox_id}")
    
    # Wait for running
    log("Waiting for sandbox to be ready...")
    for i in range(120):
        resp = requests.get(f"{APP_URL}/v1/sandboxes", headers=headers, 
                          params={"id": sandbox_id}, timeout=30)
        sandboxes = resp.json()
        if sandboxes and sandboxes[0]["status"] == "RUNNING":
            sandbox = sandboxes[0]
            session_key = sandbox["session_api_key"]
            agent_url = None
            for url_info in sandbox.get("exposed_urls", []):
                if url_info["name"] == "AGENT_SERVER":
                    agent_url = url_info["url"]
                    break
            if agent_url:
                log(f"  Agent Server: {agent_url}")
                return {
                    "sandbox_id": sandbox_id,
                    "session_api_key": session_key,
                    "agent_server_url": agent_url,
                    "headers": headers
                }
        time.sleep(2)
    
    raise TimeoutError("Sandbox did not become ready in time")


def start_conversation(sandbox_info: dict[str, Any]) -> str:
    """Start a conversation and return the agent-server conversation ID."""
    agent_url = sandbox_info["agent_server_url"]
    agent_headers = {"X-Session-API-Key": sandbox_info["session_api_key"]}
    
    # Get baseline conversations
    resp = requests.get(f"{agent_url}/api/conversations/search", 
                       headers=agent_headers, timeout=30)
    before_ids = set(c["id"] for c in resp.json().get("items", []))
    
    # Start conversation via app-server
    log("Starting conversation...")
    resp = requests.post(
        f"{APP_URL}/v1/app-conversations",
        headers=sandbox_info["headers"],
        json={
            "sandbox_id": sandbox_info["sandbox_id"],
            "initial_message": {
                "role": "user",
                "content": [{"type": "text", "text": "Say 'Ready' and nothing else."}]
            }
        },
        timeout=60
    )
    resp.raise_for_status()
    
    # Find new conversation on agent-server
    for i in range(30):
        resp = requests.get(f"{agent_url}/api/conversations/search", 
                          headers=agent_headers, timeout=30)
        after_ids = set(c["id"] for c in resp.json().get("items", []))
        new_ids = after_ids - before_ids
        if new_ids:
            conv_id = list(new_ids)[0]
            log(f"  Conversation ID: {conv_id}")
            return conv_id
        time.sleep(1)
    
    raise TimeoutError("Conversation did not appear on agent server")


def inject_secret(sandbox_info: dict[str, Any], conv_id: str) -> bool:
    """Inject a secret into the conversation."""
    agent_url = sandbox_info["agent_server_url"]
    agent_headers = {"X-Session-API-Key": sandbox_info["session_api_key"]}
    
    log(f"Injecting secret: {SECRET_NAME}={SECRET_VALUE[:20]}...")
    resp = requests.post(
        f"{agent_url}/api/conversations/{conv_id}/secrets",
        headers=agent_headers,
        json={"secrets": {SECRET_NAME: SECRET_VALUE}},
        timeout=30
    )
    
    if resp.status_code == 200:
        result = resp.json()
        log(f"  Result: {result}")
        return result.get("success", False)
    else:
        log(f"  ERROR: {resp.status_code} - {resp.text}")
        return False


def send_message(sandbox_info: dict[str, Any], conv_id: str, message: str) -> bool:
    """Send a message to the conversation."""
    agent_url = sandbox_info["agent_server_url"]
    agent_headers = {"X-Session-API-Key": sandbox_info["session_api_key"]}
    
    log(f"Sending message: {message[:50]}...")
    resp = requests.post(
        f"{agent_url}/api/conversations/{conv_id}/events",
        headers=agent_headers,
        json={
            "role": "user",
            "content": [{"type": "text", "text": message}],
            "run": True
        },
        timeout=60
    )
    
    return resp.status_code == 200


def check_events_for_secret(sandbox_info: dict[str, Any], conv_id: str) -> bool:
    """Check conversation events for evidence of the secret being used."""
    agent_url = sandbox_info["agent_server_url"]
    agent_headers = {"X-Session-API-Key": sandbox_info["session_api_key"]}
    
    log("Checking events for transformed secret...")
    resp = requests.get(
        f"{agent_url}/api/conversations/{conv_id}/events/search",
        headers=agent_headers,
        params={"limit": 100},
        timeout=60
    )
    
    if resp.status_code != 200:
        log(f"  ERROR: Could not fetch events: {resp.status_code}")
        return False
    
    events = resp.json().get("items", [])
    log(f"  Total events: {len(events)}")
    
    # Look for the transformed secret in command outputs
    expected_output = SECRET_VALUE.lower().replace("_", "_")  # lowercase version
    
    for event in events:
        obs = event.get("observation", {})
        if isinstance(obs, dict):
            content = obs.get("content", "")
            # Handle both string and list content
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text", "")
                        if "fuzzy" in text.lower():
                            return True
            elif isinstance(content, str) and "fuzzy" in content.lower():
                return True
    
    return False


def cleanup(sandbox_info: dict[str, Any]) -> None:
    """Clean up the sandbox."""
    log("Cleaning up sandbox...")
    try:
        requests.delete(
            f"{APP_URL}/v1/sandboxes/{sandbox_info['sandbox_id']}",
            headers=sandbox_info["headers"],
            timeout=30
        )
        log("  Done.")
    except Exception as e:
        log(f"  Warning: Cleanup failed: {e}")


def main() -> int:
    print("=" * 70)
    print("  PER-CONVERSATION SECRETS TEST")
    print("=" * 70)
    print()
    
    if not API_KEY:
        print("ERROR: OH_API_KEY environment variable not set")
        print("Usage: export OH_API_KEY='sk-oh-...' && python test_secrets.py")
        return 1
    
    sandbox_info = None
    try:
        # Step 1: Start sandbox
        sandbox_info = start_sandbox()
        
        # Step 2: Start conversation
        conv_id = start_conversation(sandbox_info)
        
        # Step 3: Inject secret
        if not inject_secret(sandbox_info, conv_id):
            log("ERROR: Failed to inject secret")
            return 1
        
        # Step 4: Wait for initial message to complete
        log("Waiting for initial message to complete...")
        time.sleep(15)
        
        # Step 5: Send message that uses the secret
        message = f"Run this exact command: echo ${SECRET_NAME} | tr '[:upper:]' '[:lower:]'"
        if not send_message(sandbox_info, conv_id, message):
            log("ERROR: Failed to send message")
            return 1
        
        # Step 6: Wait for agent to process
        log("Waiting for agent to execute command...")
        time.sleep(45)
        
        # Step 7: Check results
        if check_events_for_secret(sandbox_info, conv_id):
            print()
            print("=" * 70)
            print("  ✅ SUCCESS! Per-conversation secret was injected and used!")
            print(f"  Secret: {SECRET_NAME}={SECRET_VALUE}")
            print("  The secret was available as an environment variable")
            print("  and was successfully transformed by the agent.")
            print("=" * 70)
            return 0
        else:
            print()
            print("=" * 70)
            print("  ⚠️  Could not verify secret in output")
            print("  The secret injection succeeded, but we couldn't find")
            print("  evidence of it being used in the command output.")
            print("=" * 70)
            return 1
    
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    finally:
        if sandbox_info:
            cleanup(sandbox_info)


if __name__ == "__main__":
    sys.exit(main())
