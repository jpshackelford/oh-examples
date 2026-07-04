#!/usr/bin/env python3
"""Test: Can we install a custom tool package and use it via tool_module_qualnames?

This test attempts to:
1. Create a Cloud sandbox
2. Install a custom tool as a Python package  
3. Create a conversation with tool_module_qualnames pointing to the package
4. See if agent-server can import and use it

Key question: Does agent-server's Python share site-packages with pip installs?
"""

import os
import sys
import time
import requests

def log(msg):
    print(f"[TEST] {msg}")

api_key = os.getenv("OH_API_KEY")
if not api_key:
    log("ERROR: OH_API_KEY not set")
    sys.exit(1)

base_url = "https://app.all-hands.dev"
headers = {"Authorization": f"Bearer {api_key}"}

# Step 1: Create sandbox
log("Creating sandbox...")
resp = requests.post(f"{base_url}/api/v1/sandboxes", headers=headers)
resp.raise_for_status()
sandbox = resp.json()
sandbox_id = sandbox["id"]
session_key = sandbox["session_api_key"]

log(f"  Sandbox ID: {sandbox_id}")
log(f"  Status: {sandbox['status']}")

# Step 2: Wait for RUNNING
log("Waiting for sandbox to be RUNNING...")
for i in range(60):
    time.sleep(2)
    resp = requests.get(
        f"{base_url}/api/v1/sandboxes",
        headers=headers,
        params={"id": sandbox_id}
    )
    resp.raise_for_status()
    results = resp.json()
    sandbox = results[0]
    
    if sandbox["status"] == "RUNNING":
        log(f"  ✅ Sandbox RUNNING")
        break
    
    if i % 5 == 0:
        log(f"  Still waiting... (status: {sandbox['status']})")

if sandbox["status"] != "RUNNING":
    log(f"ERROR: Sandbox not RUNNING after 120s")
    sys.exit(1)

# Step 3: Get agent-server URL
agent_server = next(
    (u["url"] for u in sandbox["exposed_urls"] if u["name"] == "AGENT_SERVER"),
    None
)
if not agent_server:
    log("ERROR: No AGENT_SERVER URL found")
    sys.exit(1)

log(f"  Agent-server: {agent_server}")

# Step 4: Create custom tool package via bash
log("\nCreating custom tool package...")

bash_script = """
set -e
mkdir -p /workspace/hello_pkg/hello_pkg

cat > /workspace/hello_pkg/setup.py << 'EOF'
from setuptools import setup, find_packages
setup(name="hello-pkg", version="0.1.0", packages=find_packages())
EOF

cat > /workspace/hello_pkg/hello_pkg/__init__.py << 'EOF'
EOF

cat > /workspace/hello_pkg/hello_pkg/greet.py << 'EOF'
from typing import ClassVar
from pydantic import Field
from openhands.sdk import Action, Observation
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool

class GreetAction(Action):
    name: str = Field(..., description="Who to greet")

class GreetObservation(Observation):
    message: str = Field(..., description="Greeting")

class GreetExecutor(ToolExecutor[GreetAction, GreetObservation]):
    def __call__(self, action, conversation=None):
        msg = f"🎉 Hello {action.name}! (from custom tool)"
        return GreetObservation.from_text(text=msg, message=msg)

class GreetTool(ToolDefinition[GreetAction, GreetObservation]):
    name: ClassVar[str] = "greet"
    
    @classmethod
    def create(cls, conv_state=None):
        return [cls(
            description="Greet someone",
            action_type=GreetAction,
            observation_type=GreetObservation,
            executor=GreetExecutor()
        )]

register_tool("greet", GreetTool)
EOF

echo "Package created"
"""

resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": bash_script}
)
log(f"  Package creation: {resp.status_code}")
time.sleep(2)

# Step 5: Install the package
log("Installing package...")
resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": "cd /workspace/hello_pkg && pip install -e . 2>&1 | tail -5"}
)
log(f"  Install command: {resp.status_code}")
time.sleep(3)

# Step 6: Verify package is importable
log("Verifying package import...")
resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": "python3 -c 'import hello_pkg.greet; print(\"✅ Import successful!\")' 2>&1"}
)
log(f"  Import test: {resp.status_code}")
time.sleep(2)

# Step 7: Create conversation with custom tool
log("\nCreating conversation with custom tool...")

llm_api_key = os.getenv("LLM_API_KEY")
if not llm_api_key:
    log("  WARNING: No LLM_API_KEY, using placeholder (may fail)")
    llm_api_key = "placeholder"

payload = {
    "agent": {
        "llm": {
            "model": "gpt-4o",  # Has larger context window
            "api_key": llm_api_key
        },
        "tools": [{"name": "greet"}]
    },
    "tool_module_qualnames": {
        "greet": "hello_pkg.greet"  # Point to our installed package!
    },
    "workspace": {"working_dir": "/workspace"}
}

resp = requests.post(
    f"{agent_server}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json=payload
)

log(f"  Create conversation: {resp.status_code}")
if resp.status_code not in (200, 201):
    log(f"  ERROR: {resp.text}")
    log("\n❌ FAILED: Could not create conversation with custom tool")
    requests.delete(f"{base_url}/api/v1/sandboxes/{sandbox_id}", headers=headers)
    sys.exit(1)

conv_id = resp.json()["id"]
log(f"  ✅ Conversation: {conv_id}")

# Step 8: Test the tool
log("\nTesting custom tool...")
resp = requests.post(
    f"{agent_server}/api/conversations/{conv_id}/message",
    headers={"X-Session-API-Key": session_key},
    json={
        "content": "Use the greet tool to say hello to 'OpenHands'",
        "event_kind": "MessageEvent"
    }
)

resp = requests.post(
    f"{agent_server}/api/conversations/{conv_id}/run",
    headers={"X-Session-API-Key": session_key},
    json={}
)

log("  Waiting for execution...")
time.sleep(8)

# Step 9: Check results
resp = requests.get(
    f"{agent_server}/api/conversations/{conv_id}/events",
    headers={"X-Session-API-Key": session_key}
)

events_data = resp.json()
log(f"  Response type: {type(events_data)}")

# Handle both list and dict response formats
if isinstance(events_data, dict):
    events = events_data.get("events", [])
    log(f"  Extracted {len(events)} events from dict")
else:
    events = events_data
    log(f"  Got {len(events)} events as list")

tool_used = False
output_found = False

for event in events:
    # Events might be strings or dicts
    if isinstance(event, dict):
        if event.get("tool_name") == "greet":
            tool_used = True
            log(f"  ✅ Tool called: {event.get('action', {})}")
        
        if "Hello OpenHands" in str(event) and "custom tool" in str(event):
            output_found = True
            log(f"  ✅ Output: {event.get('content', '')[:100]}")
    
    # Also check string events
    event_str = str(event)
    if "greet" in event_str.lower() and "action" in event_str.lower():
        tool_used = True
    if "Hello OpenHands" in event_str and "custom tool" in event_str:
        output_found = True
        log(f"  ✅ Found output in event")

# Cleanup
log("\nCleaning up...")
requests.delete(f"{base_url}/api/v1/sandboxes/{sandbox_id}", headers=headers)

# Results
log("\n" + "=" * 70)
if tool_used and output_found:
    log("🎉 SUCCESS! Custom tool worked via tool_module_qualnames!")
    log("This proves that:")
    log("  1. We can install Python packages in Cloud sandbox")
    log("  2. Agent-server can import them via importlib")  
    log("  3. tool_module_qualnames enables dynamic tool loading")
    sys.exit(0)
else:
    log("❌ FAILED")
    log(f"  Tool used: {tool_used}")
    log(f"  Output found: {output_found}")
    sys.exit(1)
