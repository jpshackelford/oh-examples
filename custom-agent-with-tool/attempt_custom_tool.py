#!/usr/bin/env python3
"""Attempt to use a custom tool via agent-server APIs.

This example demonstrates the LIMITATION of trying to upload and use custom
server-side tools via agent-server APIs. It shows what seems like it should
work, where it fails, and why.

Educational purpose: Understanding the process architecture and boundaries.
"""

import json
import os
import sys

import requests


def print_section(title):
    """Print a section header."""
    print(f"\n{'=' * 70}")
    print(f"  {title}")
    print('=' * 70)


def print_step(number, description):
    """Print a step description."""
    print(f"\n[Step {number}] {description}")


def print_success(message):
    """Print a success message."""
    print(f"   ✅ {message}")


def print_failure(message):
    """Print a failure message."""
    print(f"   ❌ {message}")


def print_info(message):
    """Print an info message."""
    print(f"   ℹ️  {message}")


def main():
    print_section("Custom Tool Limitation Demonstration")
    
    # Check environment
    api_key = os.getenv("OH_API_KEY")
    if not api_key:
        print_failure("OH_API_KEY environment variable not set")
        print_info("Set it with: export OH_API_KEY=your-api-key")
        return 1
    
    cloud_api_url = os.getenv("OH_API_URL", "https://app.all-hands.dev")
    
    print_info(f"Cloud API: {cloud_api_url}")
    print_info("This example will:")
    print_info("  1. Create a sandbox")
    print_info("  2. Upload custom tool code")
    print_info("  3. Attempt to use it in a conversation")
    print_info("  4. Show where and why it fails")
    
    # Step 1: Create sandbox
    print_step(1, "Create sandbox via Cloud API")
    
    try:
        response = requests.post(
            f"{cloud_api_url}/api/v1/app-conversations",
            headers={"Authorization": f"Bearer {api_key}"},
            json={
                "initial_message": None,
                "github_token": None,
                "selected_repository": None,
            },
        )
        response.raise_for_status()
        conv_data = response.json()
        
        conversation_url = conv_data["conversation_url"]
        session_key = conv_data["session_api_key"]
        
        # Extract agent-server URL
        agent_server_url = conversation_url.split("/api/conversations/")[0]
        
        print_success(f"Sandbox created")
        print_info(f"Agent-server URL: {agent_server_url}")
        print_info(f"Session key: {session_key[:20]}...")
        
    except Exception as e:
        print_failure(f"Failed to create sandbox: {e}")
        return 1
    
    # Step 2: Upload custom tool file
    print_step(2, "Upload custom tool definition to agent-server")
    
    tool_file = "custom_tool_definition.py"
    if not os.path.exists(tool_file):
        print_failure(f"Tool file not found: {tool_file}")
        return 1
    
    try:
        with open(tool_file, "rb") as f:
            files = {"file": (tool_file, f, "text/x-python")}
            response = requests.post(
                f"{agent_server_url}/api/file/upload",
                headers={"X-Session-API-Key": session_key},
                files=files,
            )
            response.raise_for_status()
        
        upload_result = response.json()
        uploaded_path = upload_result.get("path", "/workspace/custom_tool_definition.py")
        
        print_success(f"Tool file uploaded to: {uploaded_path}")
        
    except Exception as e:
        print_failure(f"Failed to upload tool file: {e}")
        return 1
    
    # Step 3: Attempt to use custom tool in conversation
    print_step(3, "Attempt to create conversation with custom tool")
    
    print_info("We'll try the most obvious approach: send tool_module_qualnames")
    
    try:
        # This is what seems like it should work
        payload = {
            "agent": {
                "llm": {
                    "model": "gpt-4",
                    "api_key": os.getenv("LLM_API_KEY", "placeholder"),
                },
                "tools": [
                    {"name": "terminal"},
                    {"name": "file_editor"},
                    {"name": "rubber_duck"},  # Our custom tool!
                ],
            },
            "tool_module_qualnames": {
                "terminal": "openhands.tools.terminal.definition",
                "file_editor": "openhands.tools.file_editor.definition",
                "rubber_duck": "custom_tool_definition",  # Our uploaded file!
            },
            "workspace": {
                "working_dir": "/workspace",
            },
        }
        
        print_info("Sending conversation creation request...")
        print_info(f"  Tools requested: terminal, file_editor, rubber_duck")
        print_info(f"  Module qualnames: {json.dumps(payload['tool_module_qualnames'], indent=6)}")
        
        response = requests.post(
            f"{agent_server_url}/api/conversations",
            headers={"X-Session-API-Key": session_key},
            json=payload,
        )
        response.raise_for_status()
        
        conv_result = response.json()
        conversation_id = conv_result.get("id")
        
        print_success(f"Conversation created: {conversation_id}")
        print_info("But did the custom tool actually get registered?")
        
    except Exception as e:
        print_failure(f"Failed to create conversation: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print_info(f"Response: {e.response.text[:500]}")
        return 1
    
    # Step 4: Test if tool is actually available
    print_step(4, "Test if custom tool is actually usable")
    
    try:
        # Send a message that tries to use the custom tool
        message_payload = {
            "content": "Use the rubber_duck tool to debug this: print('hello)",
            "event_kind": "MessageEvent",
        }
        
        response = requests.post(
            f"{agent_server_url}/api/conversations/{conversation_id}/message",
            headers={"X-Session-API-Key": session_key},
            json=message_payload,
        )
        response.raise_for_status()
        
        print_info("Sent message requesting use of rubber_duck tool")
        
        # Run the conversation
        response = requests.post(
            f"{agent_server_url}/api/conversations/{conversation_id}/run",
            headers={"X-Session-API-Key": session_key},
            json={},
        )
        response.raise_for_status()
        
        print_info("Started conversation run...")
        print_info("Waiting a few seconds for execution...")
        
        import time
        time.sleep(5)
        
        # Get events to see what happened
        response = requests.get(
            f"{agent_server_url}/api/conversations/{conversation_id}/events",
            headers={"X-Session-API-Key": session_key},
        )
        response.raise_for_status()
        
        events = response.json()
        
        # Look for tool usage or errors
        tool_used = False
        import_error_found = False
        
        for event in events:
            if event.get("event_type") == "Action" and event.get("tool_name") == "rubber_duck":
                tool_used = True
            if "ModuleNotFoundError" in str(event) and "custom_tool_definition" in str(event):
                import_error_found = True
        
        if tool_used:
            print_success("Custom tool was successfully used!")
            print_info("This would be surprising - check the implementation!")
        elif import_error_found:
            print_failure("Import error detected - agent-server couldn't import custom_tool_definition")
            print_info("This is the expected failure!")
        else:
            print_info("Tool might not have been called, or agent worked around it")
        
    except Exception as e:
        print_failure(f"Error during conversation: {e}")
    
    # Explanation
    print_section("Why This Fails: The Process Architecture Limitation")
    
    print("""
The Fundamental Problem:
────────────────────────

Agent-server and our uploaded code run in DIFFERENT PROCESSES with
DIFFERENT Python interpreters:

    Process 1: Agent-Server (FastAPI)
    ├── Python interpreter: /usr/local/bin/python3
    ├── sys.path includes: /usr/local/lib/python3.11/site-packages/
    │   └── openhands.tools.terminal ✅ (installed package)
    └── CANNOT import: /workspace/custom_tool_definition.py ❌
                       (not in sys.path)

    Process 2: Our bash commands
    ├── If we run: python3 /workspace/custom_tool_definition.py
    └── This runs in a subprocess, separate from agent-server

When we send tool_module_qualnames:
───────────────────────────────────

    {
      "rubber_duck": "custom_tool_definition"
    }

Agent-server tries:
──────────────────

    import importlib
    importlib.import_module("custom_tool_definition")
    
    ❌ ModuleNotFoundError: No module named 'custom_tool_definition'

Why? Because /workspace/ is NOT in agent-server's sys.path!

What Would Make It Work:
────────────────────────

Option 1: Install as package before agent-server starts
   └─ pip install /workspace/custom_tool_package/
   └─ Restart agent-server
   └─ Then importlib.import_module() would succeed

Option 2: Use client-side tools
   └─ Tool executes in OUR process, not agent-server
   └─ Agent-server just knows the tool exists
   └─ See ../custom-agent-client-side-tool/ for this pattern

Option 3: Pre-built custom agent-server image
   └─ Docker image with custom tools pre-installed
   └─ Deploy that image instead of standard agent-server

What IS Possible Today:
──────────────────────

✅ Configure which built-in tools agent has (see ../custom-agent-no-browser/)
✅ Create custom tools locally via SDK (run SDK on your machine)
✅ Use client-side tools (tool execution in client process)
✅ Load plugins that install as packages

❌ Upload arbitrary Python file and use it as server-side tool
❌ Custom server-side tools via simple API calls
    """)
    
    # Cleanup
    print_section("Cleanup")
    
    try:
        response = requests.post(
            f"{agent_server_url}/api/end",
            headers={"X-Session-API-Key": session_key},
        )
        print_success("Sandbox cleaned up")
    except Exception:
        print_info("Cleanup skipped (sandbox will auto-expire)")
    
    print_section("Summary")
    print("""
This example demonstrated:
  1. ✅ How to upload files to agent-server
  2. ✅ How to send tool_module_qualnames
  3. ❌ Why custom server-side tools don't work via simple upload
  4. 💡 What the architectural limitation is (process isolation)
  5. 💡 What alternatives exist (client-side tools, packages, pre-built images)

The key insight: Agent-server can only import modules in its Python environment.
Uploaded files are just files on disk, not importable Python modules (unless
they're in sys.path or installed as packages).

For working examples of what IS possible, see:
  - ../custom-agent-no-browser/     (configure built-in tools)
  - ../custom-agent-client-side/    (client-side tool execution)
    """)
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
