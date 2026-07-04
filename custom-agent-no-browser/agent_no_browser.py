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
LLM_API_KEY = os.getenv("LLM_API_KEY")  # OpenHands LiteLLM proxy key
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://llm-proxy.app.all-hands.dev/")
LLM_MODEL = os.getenv("LLM_MODEL", "litellm_proxy/claude-sonnet-4-5-20250929")

if not API_KEY:
    print("Error: OH_API_KEY environment variable not set", file=sys.stderr)
    sys.exit(1)

if not LLM_API_KEY:
    print("Error: LLM_API_KEY environment variable not set", file=sys.stderr)
    print("  Get your key from: https://app.all-hands.dev -> Profile -> API Keys")
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
    kwargs.setdefault("timeout", 30)
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
    kwargs.setdefault("timeout", 30)
    response = requests.request(method, url, headers=headers, **kwargs)
    response.raise_for_status()
    return response


def create_sandbox() -> tuple[str, str, str]:
    """Create a sandbox via Cloud API.
    
    Returns:
        (sandbox_id, session_key, agent_server_url)
    """
    print("\n=== Creating sandbox via Cloud API ===")
    
    # Create sandbox directly
    response = cloud_api_request("POST", "/api/v1/sandboxes")
    sandbox = response.json()
    sandbox_id = sandbox["id"]
    print(f"  sandbox: {sandbox_id}")
    
    # Wait for sandbox to be ready
    print("  waiting for sandbox...")
    for i in range(90):
        response = cloud_api_request(
            "GET",
            "/api/v1/sandboxes",
            params={"id": sandbox_id}
        )
        results = response.json()
        if not results or results[0] is None:
            time.sleep(2)
            continue
        sandbox = results[0]
        
        status = sandbox.get("status", "")
        if i % 5 == 0:
            print(f"    status: {status}")
        
        if status == "RUNNING":
            session_key = sandbox["session_api_key"]
            # Extract agent-server URL from exposed_urls
            agent_server_url = next(
                (u["url"] for u in sandbox["exposed_urls"] if u["name"] == "AGENT_SERVER"),
                None
            )
            if not agent_server_url:
                raise RuntimeError("No AGENT_SERVER URL found in sandbox")
            
            print(f"  ✓ sandbox ready: {sandbox_id}")
            print(f"  agent-server: {agent_server_url}")
            
            return sandbox_id, session_key, agent_server_url
        
        time.sleep(2)
    
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
    
    # LLM configuration is required for agent-server API
    # Must include both api_key AND base_url for the LiteLLM proxy
    llm_config = {
        "model": LLM_MODEL,
        "api_key": LLM_API_KEY,
        "base_url": LLM_BASE_URL,
    }
    
    custom_tools = [
        {"name": "terminal"},
        {"name": "file_editor"},
        {"name": "task_tracker"},
    ]
    
    payload = {
        "agent": {
            "llm": llm_config,
        },
        "workspace": {"working_dir": "/workspace"},
        "initial_message": {
            "content": [{"text": TASK}]
        }
    }
    
    if method == "inline":
        # Pass tools directly in conversation creation
        payload["agent"]["tools"] = custom_tools
        print("  passing tools inline in conversation creation")
    else:
        # Tools come from PATCH /api/settings configuration
        print("  using tools from agent-server settings")
    
    print(f"  model: {LLM_MODEL}")
    print(f"  base_url: {LLM_BASE_URL}")
    
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
    
    # Try to start the conversation (may already be running due to initial_message)
    try:
        agent_server_request(
            "POST",
            agent_server_url,
            session_key,
            f"/api/conversations/{conv_id}/run",
        )
        print("  conversation started")
    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 409:
            print("  conversation already running")
        else:
            raise
    
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


def get_available_tools(agent_server_url: str, session_key: str, conv_id: str) -> list[dict]:
    """Get the list of tools that were available to the agent.
    
    This retrieves the SystemPromptEvent which contains the actual tools array
    that was configured for the conversation.
    
    Returns:
        List of tool definitions, each with 'title', 'kind', 'description', etc.
    """
    response = agent_server_request(
        "GET",
        agent_server_url,
        session_key,
        f"/api/conversations/{conv_id}/events/search?kind__eq=SystemPromptEvent&limit=1",
    )
    
    data = response.json()
    events = data.get("items", [])
    
    if not events:
        return []
    
    # SystemPromptEvent contains the tools array
    system_event = events[0]
    return system_event.get("tools", [])


def display_tools(tools: list[dict], show_descriptions: bool = False) -> None:
    """Display tools in a concise, grouped format.
    
    Groups tools by category (e.g., all browser tools together) for readability.
    
    Args:
        tools: List of tool definitions from SystemPromptEvent
        show_descriptions: If True, show first line of each tool's description
    """
    if not tools:
        print("  (no tools found)")
        return
    
    # Group tools by category based on title prefix
    categorized = {}
    for tool in tools:
        title = tool.get("title", "unknown")
        
        # Categorize based on title prefix
        if title.startswith("browser_"):
            category = "browser"
        elif title.startswith("default_"):
            # MCP tools like default_create_pr, default_tavily_*
            # Extract the provider name
            parts = title.split("_", 2)
            category = parts[1] if len(parts) > 1 else "default"
        else:
            category = "core"
        
        if category not in categorized:
            categorized[category] = []
        categorized[category].append(tool)
    
    # Display tools by category
    print(f"  total tools: {len(tools)}")
    print()
    
    for category in sorted(categorized.keys()):
        tools_in_cat = categorized[category]
        
        if category == "browser":
            print(f"  📱 Browser tools ({len(tools_in_cat)}):")
        elif category == "core":
            print(f"  🔧 Core tools ({len(tools_in_cat)}):")
        else:
            print(f"  🔌 {category.title()} tools ({len(tools_in_cat)}):")
        
        for tool in tools_in_cat:
            title = tool.get("title", "unknown")
            kind = tool.get("kind", "unknown")
            
            if show_descriptions:
                desc = tool.get("description", "")
                # Get first line of description
                first_line = desc.split("\n")[0] if desc else ""
                print(f"    • {title} ({kind})")
                print(f"      {first_line[:70]}{'...' if len(first_line) > 70 else ''}")
            else:
                print(f"    • {title}")
        print()


def check_browser_tools(tools: list[dict]) -> bool:
    """Check if browser tools are present in the tools list.
    
    Args:
        tools: List of tool definitions
        
    Returns:
        True if browser tools are found, False otherwise
    """
    for tool in tools:
        title = tool.get("title", "")
        kind = tool.get("kind", "")
        
        # Check if this is a browser tool
        if "browser" in title.lower() or "browser" in kind.lower():
            return True
    
    return False


def verify_tools(agent_server_url: str, session_key: str, conv_id: str) -> None:
    """Verify which tools were actually available to the agent.
    
    This inspects the conversation events to see:
    1. Which tools were available (from SystemPromptEvent)
    2. Which tools were actually used (from ActionEvents)
    3. Whether browser tools are present
    """
    print("\n=== Verifying tools ===")
    
    # Get available tools from SystemPromptEvent
    available_tools = get_available_tools(agent_server_url, session_key, conv_id)
    
    if available_tools:
        print("\n  Available tools:")
        display_tools(available_tools)
        
        # Check for browser tools in available tools
        has_browser = check_browser_tools(available_tools)
        if has_browser:
            print("  ❌ FAIL: Browser tools are in the available tools list!", file=sys.stderr)
        else:
            print("  ✅ PASS: No browser tools in available tools list")
    else:
        print("  ⚠️  Could not retrieve available tools (no SystemPromptEvent found)")
    
    # Get tools actually used from ActionEvents
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
    
    print(f"\n  Tools actually used: {sorted(tools_used) if tools_used else '(none)'}")
    
    if "browser" in tools_used or any("browser" in t.lower() for t in tools_used):
        print("  ❌ FAIL: Browser tool was used!", file=sys.stderr)
        return False
    else:
        print("  ✅ PASS: No browser tools were used")
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
