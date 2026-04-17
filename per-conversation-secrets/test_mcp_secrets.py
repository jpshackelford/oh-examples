#!/usr/bin/env python3
"""
End-to-end test for per-conversation secrets with MCP server validation.

This script demonstrates the FULL workflow:
1. Start an MCP server locally (accessible via work host URL) that expects a specific token
2. Start a sandbox and conversation
3. Inject the secret token via REST API
4. Have the agent call the MCP tool - the server validates the token was passed correctly

The key insight: Secrets injected via the API become environment variables available to
bash commands. For MCP authentication, we can either:
a) Use an MCP server that reads the token from an env var in the sandbox
b) Have the agent explicitly pass the token when calling the MCP tool

This test uses approach (a) by running an MCP server that the agent can reach.

Prerequisites:
    - OH_API_KEY environment variable
    - Port 12000 available (for MCP server on work host)

Usage:
    export OH_API_KEY="sk-oh-..."
    python test_mcp_secrets.py
"""

import os
import sys
import time
import json
import subprocess
import requests
from typing import Any

# Configuration
API_KEY = os.environ.get('OH_API_KEY', '')
APP_URL = "https://app.all-hands.dev/api"
MCP_SERVER_PORT = 12000

# The secret we'll inject and validate
SECRET_NAME = "MCP_AUTH_TOKEN"
SECRET_VALUE = "super-secret-token-12345-fuzzy-bear"


def log(msg: str) -> None:
    """Print with timestamp."""
    print(f"[{time.strftime('%H:%M:%S')}] {msg}")


def start_mcp_server() -> subprocess.Popen:
    """Start the MCP token validator server on port 12000 (work-1 host)."""
    log(f"Starting MCP server on port {MCP_SERVER_PORT}...")
    
    script_dir = os.path.dirname(os.path.abspath(__file__))
    server_script = os.path.join(script_dir, "mcp_server.py")
    
    proc = subprocess.Popen(
        ["python", server_script, "--port", str(MCP_SERVER_PORT), "--expected-token", SECRET_VALUE],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE
    )
    
    # Wait for server to start
    time.sleep(2)
    
    # Verify it's running
    try:
        resp = requests.get(f"http://localhost:{MCP_SERVER_PORT}/health", timeout=5)
        if resp.status_code == 200:
            log(f"  MCP server started successfully")
            return proc
    except Exception as e:
        log(f"  Failed to verify server: {e}")
    
    # Server didn't start
    proc.terminate()
    raise RuntimeError("Failed to start MCP server")


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
            work_1_url = None
            for url_info in sandbox.get("exposed_urls", []):
                if url_info["name"] == "AGENT_SERVER":
                    agent_url = url_info["url"]
                elif url_info["name"] == "WORK_1":
                    work_1_url = url_info["url"]
            if agent_url:
                log(f"  Agent Server: {agent_url}")
                if work_1_url:
                    log(f"  Work-1 URL: {work_1_url}")
                
                return {
                    "sandbox_id": sandbox_id,
                    "session_api_key": session_key,
                    "agent_server_url": agent_url,
                    "work_1_url": work_1_url,
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
    """Inject the MCP auth token secret into the conversation."""
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
    
    log(f"Sending message...")
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


def get_events(sandbox_info: dict[str, Any], conv_id: str) -> list[dict]:
    """Get all events from the conversation."""
    agent_url = sandbox_info["agent_server_url"]
    agent_headers = {"X-Session-API-Key": sandbox_info["session_api_key"]}
    
    resp = requests.get(
        f"{agent_url}/api/conversations/{conv_id}/events/search",
        headers=agent_headers,
        params={"limit": 100},
        timeout=60
    )
    
    if resp.status_code == 200:
        return resp.json().get("items", [])
    return []


def check_secret_in_output(events: list[dict], expected_substring: str) -> bool:
    """Check if expected substring appears in any command output."""
    for event in events:
        obs = event.get("observation", {})
        if isinstance(obs, dict):
            content = obs.get("content", "")
            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict):
                        text = item.get("text", "")
                        if expected_substring.lower() in text.lower():
                            return True
            elif isinstance(content, str):
                if expected_substring.lower() in content.lower():
                    return True
    return False


def cleanup(sandbox_info: dict[str, Any] = None, mcp_proc: subprocess.Popen = None) -> None:
    """Clean up resources."""
    log("Cleaning up...")
    
    if mcp_proc:
        log("  Stopping MCP server...")
        mcp_proc.terminate()
        try:
            mcp_proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            mcp_proc.kill()
    
    if sandbox_info:
        log("  Deleting sandbox...")
        try:
            requests.delete(
                f"{APP_URL}/v1/sandboxes/{sandbox_info['sandbox_id']}",
                headers=sandbox_info["headers"],
                timeout=30
            )
        except Exception as e:
            log(f"  Warning: Sandbox cleanup failed: {e}")
    
    log("  Done.")


def main() -> int:
    print("=" * 70)
    print("  PER-CONVERSATION SECRETS WITH MCP VALIDATION TEST")
    print("=" * 70)
    print()
    
    if not API_KEY:
        print("ERROR: OH_API_KEY environment variable not set")
        print("Usage: export OH_API_KEY='sk-oh-...' && python test_mcp_secrets.py")
        return 1
    
    mcp_proc = None
    sandbox_info = None
    
    try:
        # Step 1: Start MCP server locally (accessible via work host URL)
        mcp_proc = start_mcp_server()
        
        # Step 2: Start sandbox
        sandbox_info = start_sandbox()
        
        # Get the work-1 URL where our MCP server is accessible
        # This is the URL that the sandbox agent can use to reach our local server
        work_1_url = sandbox_info.get("work_1_url")
        if not work_1_url:
            # Derive it from agent URL pattern
            import re
            match = re.match(r'https://([^.]+)\.prod-runtime\.all-hands\.dev', 
                           sandbox_info["agent_server_url"])
            if match:
                sandbox_runtime_id = match.group(1)
                work_1_url = f"https://work-1-{sandbox_runtime_id}.prod-runtime.all-hands.dev"
        
        log(f"MCP Server accessible at: {work_1_url}")
        
        # Step 3: Start conversation
        conv_id = start_conversation(sandbox_info)
        
        # Step 4: Inject the secret
        if not inject_secret(sandbox_info, conv_id):
            log("ERROR: Failed to inject secret")
            return 1
        
        # Step 5: Wait for initial message to complete
        log("Waiting for initial message to complete...")
        time.sleep(15)
        
        # Step 6: Ask agent to test the secret by calling our MCP server
        # The agent will use curl to call our MCP server with the secret token
        message = f"""I need you to verify that a secret token is working.

1. First, run this command to verify the secret is available:
   echo "Secret available: $MCP_AUTH_TOKEN" | head -c 30

2. Then, call our validation server using curl:
   curl -X POST "{work_1_url}/mcp" \\
     -H "Content-Type: application/json" \\
     -H "Authorization: Bearer $MCP_AUTH_TOKEN" \\
     -d '{{"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {{"name": "validate_token", "arguments": {{"echo_message": "Secret injection test"}}}}}}'

Report the results of both commands."""
        
        if not send_message(sandbox_info, conv_id, message):
            log("ERROR: Failed to send message")
            return 1
        
        # Step 7: Wait for agent to process
        log("Waiting for agent to execute commands...")
        time.sleep(60)
        
        # Step 8: Check results
        events = get_events(sandbox_info, conv_id)
        log(f"Retrieved {len(events)} events")
        
        # Check for successful token validation
        found_secret = check_secret_in_output(events, "super-secret")
        found_success = check_secret_in_output(events, "SUCCESS") and check_secret_in_output(events, "Token validated")
        
        print()
        print("=" * 70)
        if found_secret and found_success:
            print("  ✅ FULL SUCCESS!")
            print(f"  - Secret '{SECRET_NAME}' was injected via REST API")
            print(f"  - Secret was available as environment variable in bash")
            print(f"  - MCP server received and validated the token")
            print("=" * 70)
            return 0
        elif found_secret:
            print("  ⚠️  PARTIAL SUCCESS")
            print(f"  - Secret '{SECRET_NAME}' was injected and available")
            print(f"  - But MCP validation response not found in output")
            print("  - Check if the MCP server received the request")
            print("=" * 70)
            return 1
        else:
            print("  ❌ FAILED")
            print("  - Could not verify secret was available")
            print("  - Check the conversation events for details")
            print("=" * 70)
            
            # Dump some events for debugging
            log("\nRecent events for debugging:")
            for event in events[-5:]:
                log(json.dumps(event, indent=2, default=str)[:500])
            
            return 1
    
    except Exception as e:
        log(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1
    
    finally:
        cleanup(sandbox_info, mcp_proc)


if __name__ == "__main__":
    sys.exit(main())
