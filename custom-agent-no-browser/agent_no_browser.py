#!/usr/bin/env python3
"""Configure an agent with custom tools (no browser).

This example demonstrates the correct pattern for customizing agent tools:
1. Create a sandbox via the Cloud API
2. Get the session API key and agent-server URL from the sandbox
3. Create a conversation on the agent-server, passing the desired tools inline
4. Run the conversation and verify the expected tools are present and the
   browser tool is excluded
5. Delete the conversation and sandbox

Key insight: There are two APIs. The Cloud API (app.all-hands.dev) manages the
sandbox lifecycle, while the agent-server API (running inside the sandbox)
controls agent configuration. Tools must be configured on the agent-server.

The reliable way to do this is to pass the tool list inline in the
`agent` object when creating the conversation. That request creates the full
agent spec (LLM + tools) in one shot, so the tools always take effect.
"""

import argparse
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

# Tools the agent should have access to (browser is excluded by omission).
# The agent-server always adds "finish" and "think" automatically, so the
# resulting conversation exposes these three plus those two.
EXPECTED_TOOLS = ["terminal", "file_editor", "task_tracker"]


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


def create_conversation_with_custom_tools(
    agent_server_url: str, session_key: str
) -> str:
    """Create a conversation with custom tools passed inline.

    The tool list is passed in the `agent` object so the full agent spec
    (LLM + tools) is created in a single request and the tools always apply.

    Returns:
        conversation_id
    """
    print("\n=== Creating conversation ===")

    # LLM configuration is required for the agent-server API.
    # Must include both api_key AND base_url for the LiteLLM proxy.
    llm_config = {
        "model": LLM_MODEL,
        "api_key": LLM_API_KEY,
        "base_url": LLM_BASE_URL,
    }

    payload = {
        "agent": {
            "llm": llm_config,
            "tools": [{"name": name} for name in EXPECTED_TOOLS],
        },
        "workspace": {"working_dir": "/workspace"},
        "initial_message": {
            "content": [{"text": TASK}]
        }
    }

    print(f"  model: {LLM_MODEL}")
    print(f"  base_url: {LLM_BASE_URL}")
    print(f"  tools: {', '.join(EXPECTED_TOOLS)}")

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


def verify_tools(agent_server_url: str, session_key: str, conv_id: str) -> bool:
    """Verify the agent got the intended tools and no browser tools.

    Checks two things:
    1. The expected tools (EXPECTED_TOOLS) are all present in the
       SystemPromptEvent, and no browser tool is present.
    2. No browser tool was actually used in any ActionEvent.

    Returns True only if every check passes.
    """
    print("\n=== Verifying tools ===")
    ok = True

    # Get available tools from the SystemPromptEvent.
    available_tools = get_available_tools(agent_server_url, session_key, conv_id)

    if available_tools:
        print("\n  Available tools:")
        display_tools(available_tools)

        available_titles = {t.get("title", "") for t in available_tools}

        # a) All expected tools must be present.
        missing = [name for name in EXPECTED_TOOLS if name not in available_titles]
        if missing:
            ok = False
            print(
                f"  ❌ FAIL: expected tools missing from conversation: {missing}",
                file=sys.stderr,
            )
        else:
            print(f"  ✅ PASS: all expected tools present: {EXPECTED_TOOLS}")

        # b) No browser tools should be present.
        if check_browser_tools(available_tools):
            ok = False
            print("  ❌ FAIL: browser tools are in the available tools list!", file=sys.stderr)
        else:
            print("  ✅ PASS: no browser tools in available tools list")
    else:
        ok = False
        print(
            "  ❌ FAIL: could not retrieve available tools (no SystemPromptEvent found)",
            file=sys.stderr,
        )

    # Get tools actually used from ActionEvents.
    response = agent_server_request(
        "GET",
        agent_server_url,
        session_key,
        f"/api/conversations/{conv_id}/events/search?limit=100",
    )

    data = response.json()
    events = data.get("items", [])

    tools_used = set()
    for event in events:
        if event.get("kind") == "ActionEvent" and "tool_name" in event:
            tools_used.add(event["tool_name"])

    print(f"\n  Tools actually used: {sorted(tools_used) if tools_used else '(none)'}")

    if any("browser" in t.lower() for t in tools_used):
        ok = False
        print("  ❌ FAIL: browser tool was used!", file=sys.stderr)
    else:
        print("  ✅ PASS: no browser tools were used")

    return ok


def cleanup(agent_server_url: str, session_key: str, conv_id: str, sandbox_id: str) -> None:
    """Delete the conversation and sandbox."""
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
        # DELETE /api/v1/sandboxes/{id} requires sandbox_id as BOTH a path
        # segment and a query parameter, otherwise it returns HTTP 422.
        cloud_api_request(
            "DELETE",
            f"/api/v1/sandboxes/{sandbox_id}",
            params={"sandbox_id": sandbox_id},
        )
        print(f"  ✓ deleted sandbox {sandbox_id}")
    except Exception as e:
        print(f"  ⚠️  failed to delete sandbox: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(description="Configure agent with custom tools")
    parser.add_argument(
        "--keep",
        action="store_true",
        help="Keep the conversation and sandbox after completion (for inspection)",
    )
    args = parser.parse_args()

    sandbox_id = None
    session_key = None
    agent_server_url = None
    conv_id = None
    try:
        # 1. Create sandbox
        sandbox_id, session_key, agent_server_url = create_sandbox()

        # 2. Create conversation with the desired tools passed inline
        conv_id = create_conversation_with_custom_tools(
            agent_server_url, session_key
        )

        # 3. Run conversation
        run_conversation(agent_server_url, session_key, conv_id)

        # 4. Verify tools
        passed = verify_tools(agent_server_url, session_key, conv_id)

        # 5. Show results
        print("\n=== Results ===")
        print(f"View conversation: {CLOUD_API_URL}/conversations/{conv_id}")
        print(f"Agent-server: {agent_server_url}")

        # 6. Cleanup (unless --keep)
        if not args.keep:
            cleanup(agent_server_url, session_key, conv_id, sandbox_id)
        else:
            print("\n=== Keeping resources (--keep flag) ===")
            print(f"Conversation ID: {conv_id}")
            print(f"Sandbox ID: {sandbox_id}")
            print(f"Session key: {session_key[:20]}...")

        if not passed:
            print("\n❌ Verification failed: see FAIL messages above.", file=sys.stderr)
            sys.exit(1)
        print("\n✅ Success: agent configured with the expected tools (no browser).")

    except Exception as e:
        print(f"\n❌ Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        # Best-effort cleanup so we don't leak a sandbox on failure.
        if sandbox_id and not args.keep:
            try:
                cleanup(agent_server_url, session_key, conv_id, sandbox_id)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
