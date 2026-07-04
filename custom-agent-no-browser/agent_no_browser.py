#!/usr/bin/env python3
"""Configure an agent-server with custom tools (no browser).

This example demonstrates the correct pattern for customizing agent tools:
1. Create a sandbox via Cloud API
2. Get the session API key and agent-server URL
3. Configure the agent-server with custom tools via PATCH /api/settings
4. Create a conversation - it uses the configured tools
5. Verify that browser tools are actually excluded

Key insight: You cannot configure tools via the Cloud API's
POST /api/v1/app-conversations endpoint. Instead, you must:
- Call the agent-server API directly using the session key
- Configure tools via PATCH /api/settings before creating conversations
- OR pass tools directly when creating each conversation

This example shows both approaches.
"""

import argparse
import json
import os
import sys
import time

import requests

# Configuration
CLOUD_API_URL = os.getenv("OPENHANDS_CLOUD_API_URL", "https://app.all-hands.dev")
API_KEY = os.getenv("OH_API_KEY")

if not API_KEY:
    print("Error: OH_API_KEY environment variable not set", file=sys.stderr)
    sys.exit(1)

TASK = (
    "Create a Python script called 'hello.py' that prints 'Hello, Custom Agent!' "
    "Then show me the file content to confirm it was created."
)


def cloud_api_request(method: str, path: str, **kwargs) -> requests.Response:
    """Make a request to the Cloud API."""
    url = f"{CLOUD_API_URL}{path}"
    headers = kwargs.pop("headers", {})
    headers["Authorization"] = f"Bearer {API_KEY}"
    response = requests.request(method, url, headers=headers, **kwargs)
    response.raise_for_status()
    return response


def agent_server_request(
    method: str, agent_server_url: str, session_key: str, path: str, **kwargs
) -> requests.Response:
    """Make a request to the agent-server."""
    url = f"{agent_server_url}{path}"
    headers = kwargs.pop("headers", {})
    headers["X-Session-API-Key"] = session_key
    response = requests.request(method, url, headers=headers, **kwargs)
    response.raise_for_status()
    return response


def create_sandbox() -> tuple[str, str, str]:
    """Create a sandbox via Cloud API.
    
    Returns:
        (sandbox_id, session_key, agent_server_url)
    """
    print("\n=== Creating sandbox via Cloud API ===")
    
    # Create a minimal conversation just to get a sandbox
    response = cloud_api_request(
        "POST",
        "/api/v1/app-conversations",
        json={
            "github_token": None,
            "selected_repository": None,
        },
    )
    
    data = response.json()
    conv_id = data["id"]
    print(f"  conversation: {conv_id}")
    
    # Wait for sandbox to be ready
    print("  waiting for sandbox...")
    for _ in range(60):
        response = cloud_api_request("GET", f"/api/v1/app-conversations?ids={conv_id}")
        conv = response.json()[0]
        
        if conv.get("sandbox_status") == "RUNNING":
            sandbox_id = conv["sandbox_id"]
            session_key = conv["session_api_key"]
            # Extract agent-server URL from conversation_url
            conv_url = conv["conversation_url"]
            agent_server_url = conv_url.rsplit("/api/conversations/", 1)[0]
            
            print(f"  ✓ sandbox ready: {sandbox_id}")
            print(f"  agent-server: {agent_server_url}")
            
            # Clean up the temp conversation
            cloud_api_request("DELETE", f"/api/v1/app-conversations/{conv_id}")
            print(f"  cleaned up temp conversation")
            
            return sandbox_id, session_key, agent_server_url
        
        time.sleep(1)
    
    raise TimeoutError("Sandbox did not reach RUNNING status")


def configure_agent_tools(agent_server_url: str, session_key: str) -> None:
    """Configure the agent-server with custom tools (no browser).
    
    This uses PATCH /api/settings to set the default tools for all future
    conversations on this agent-server instance.
    """
    print("\n=== Configuring agent-server with custom tools ===")
    
    custom_tools = [
        {"name": "terminal"},
        {"name": "file_editor"},
        {"name": "task_tracker"},
    ]
    
    response = agent_server_request(
        "PATCH",
        agent_server_url,
        session_key,
        "/api/settings",
        json={
            "agent_settings_diff": {
                "tools": custom_tools,
            }
        },
    )
    
    data = response.json()
    configured_tools = data["agent_settings"]["tools"]
    
    print(f"  ✓ configured {len(configured_tools)} tools:")
    for tool in configured_tools:
        print(f"    - {tool['name']}")
    
    # Verify browser is NOT in the list
    tool_names = [t["name"] for t in configured_tools]
    if "browser_tool_set" in tool_names:
        print("  ⚠️  WARNING: browser_tool_set is still present!", file=sys.stderr)
    else:
        print("  ✓ browser_tool_set successfully excluded")


def create_conversation_with_custom_tools(
    agent_server_url: str, session_key: str, method: str = "settings"
) -> str:
    """Create a conversation with custom tools.
    
    Args:
        method: Either "settings" (use server-configured tools) or 
                "inline" (pass tools in conversation creation)
    
    Returns:
        conversation_id
    """
    print(f"\n=== Creating conversation (method: {method}) ===")
    
    payload = {
        "initial_message": {
            "content": [{"text": TASK}]
        }
    }
    
    if method == "inline":
        # Pass tools directly in conversation creation
        payload["agent"] = {
            "tools": [
                {"name": "terminal"},
                {"name": "file_editor"},
                {"name": "task_tracker"},
            ]
        }
        print("  passing tools inline in conversation creation")
    else:
        print("  using tools from agent-server settings")
    
    response = agent_server_request(
        "POST",
        agent_server_url,
        session_key,
        "/api/conversations",
        json=payload,
    )
    
    data = response.json()
    conv_id = data["id"]
    print(f"  ✓ conversation created: {conv_id}")
    
    return conv_id


def run_conversation(agent_server_url: str, session_key: str, conv_id: str) -> None:
    """Run the conversation and wait for completion."""
    print("\n=== Running conversation ===")
    
    # Start the conversation
    agent_server_request(
        "POST",
        agent_server_url,
        session_key,
        f"/api/conversations/{conv_id}/run",
    )
    print("  conversation started")
    
    # Poll for completion
    print("  waiting for completion...")
    for i in range(180):  # 3 minute timeout
        response = agent_server_request(
            "GET",
            agent_server_url,
            session_key,
            f"/api/conversations/{conv_id}",
        )
        data = response.json()
        status = data.get("execution_status", "unknown")
        
        if i % 5 == 0:  # Print status every 5 seconds
            print(f"    execution_status: {status}")
        
        if status == "finished":
            print("  ✓ conversation completed successfully")
            return
        elif status == "error":
            print("  ✗ conversation failed", file=sys.stderr)
            return
        
        time.sleep(1)
    
    print("  ⚠️  timeout waiting for completion", file=sys.stderr)


def verify_tools(agent_server_url: str, session_key: str, conv_id: str) -> None:
    """Verify which tools were actually available to the agent.
    
    This inspects the conversation events to see which tools were used.
    """
    print("\n=== Verifying tools ===")
    
    response = agent_server_request(
        "GET",
        agent_server_url,
        session_key,
        f"/api/conversations/{conv_id}/events/search?limit=100",
    )
    
    data = response.json()
    events = data.get("items", [])
    
    # Extract unique tool names from ActionEvents
    tools_used = set()
    for event in events:
        if event.get("kind") == "ActionEvent" and "tool_name" in event:
            tools_used.add(event["tool_name"])
    
    print(f"  tools actually used: {sorted(tools_used)}")
    
    if "browser" in tools_used or "browser_tool_set" in tools_used:
        print("  ⚠️  WARNING: Browser tool was used!", file=sys.stderr)
        return False
    else:
        print("  ✓ Browser tool was NOT used - configuration worked!")
        return True


def cleanup(agent_server_url: str, session_key: str, conv_id: str, sandbox_id: str) -> None:
    """Clean up conversation and sandbox."""
    print("\n=== Cleanup ===")
    
    try:
        agent_server_request(
            "DELETE",
            agent_server_url,
            session_key,
            f"/api/conversations/{conv_id}",
        )
        print(f"  ✓ deleted conversation {conv_id}")
    except Exception as e:
        print(f"  ⚠️  failed to delete conversation: {e}", file=sys.stderr)
    
    try:
        cloud_api_request("DELETE", f"/api/v1/sandboxes/{sandbox_id}")
        print(f"  ✓ deleted sandbox {sandbox_id}")
    except Exception as e:
        print(f"  ⚠️  failed to delete sandbox: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Configure agent with custom tools")
    parser.add_argument(
        "--method",
        choices=["settings", "inline"],
        default="settings",
        help="How to specify tools: 'settings' (via PATCH /api/settings) or 'inline' (in conversation creation)",
    )
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the conversation and sandbox after completion (for inspection)",
    )
    args = parser.parse_args()
    
    try:
        # 1. Create sandbox
        sandbox_id, session_key, agent_server_url = create_sandbox()
        
        # 2. Configure tools (only if using settings method)
        if args.method == "settings":
            configure_agent_tools(agent_server_url, session_key)
        
        # 3. Create conversation
        conv_id = create_conversation_with_custom_tools(
            agent_server_url, session_key, method=args.method
        )
        
        # 4. Run conversation
        run_conversation(agent_server_url, session_key, conv_id)
        
        # 5. Verify tools
        verify_tools(agent_server_url, session_key, conv_id)
        
        # 6. Show results
        print("\n=== Results ===")
        print(f"View conversation: {CLOUD_API_URL}/conversations/{conv_id}")
        print(f"Agent-server: {agent_server_url}")
        
        # 7. Cleanup (unless --keep)
        if not args.keep:
            cleanup(agent_server_url, session_key, conv_id, sandbox_id)
        else:
            print("\n=== Keeping resources (--keep flag) ===")
            print(f"Conversation ID: {conv_id}")
            print(f"Sandbox ID: {sandbox_id}")
            print(f"Session key: {session_key[:20]}...")
    
    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
