#!/usr/bin/env python3
"""Experiment: Can we install a custom tool and use it via tool_module_qualnames?"""

import os
import sys
import json
import time
import requests

def log(msg):
    print(f"[TEST] {msg}")

# Check API key
api_key = os.getenv("OH_API_KEY")
if not api_key:
    log("ERROR: OH_API_KEY not set")
    sys.exit(1)

cloud_api = "https://app.all-hands.dev"

# Step 1: Create sandbox
log("Creating sandbox...")
resp = requests.post(
    f"{cloud_api}/api/v1/app-conversations",
    headers={"Authorization": f"Bearer {api_key}"},
    json={"initial_message": None}
)
resp.raise_for_status()
data = resp.json()

# Poll until sandbox is ready
request_id = data["id"]
log(f"Request ID: {request_id}, waiting for sandbox...")

for i in range(60):  # Wait up to 60 seconds
    time.sleep(1)
    resp = requests.get(
        f"{cloud_api}/api/v1/app-conversations/{request_id}",
        headers={"Authorization": f"Bearer {api_key}"}
    )
    data = resp.json()
    
    if data.get("agent_server_url"):
        break
    
    if i % 5 == 0:
        log(f"  Still waiting... (status: {data.get('status')})")

agent_server = data["agent_server_url"]
if not agent_server:
    log(f"ERROR: Sandbox not ready after 60s: {data}")
    sys.exit(1)

# Get session key - need to check the response for correct field
log(f"Sandbox ready: {agent_server}")

# The session key is likely returned when creating a conversation
# Let me create a conversation on the agent-server to get the session key
resp = requests.post(
    f"{agent_server}/api/sessions",
    json={}
)
session_data = resp.json()
session_key = session_data.get("session_api_key") or session_data.get("api_key")

log(f"Session key: {session_key[:20] if session_key else 'NOT FOUND'}...")

# Step 2: Create a simple custom tool package
log("\nCreating custom tool package...")

# Tool implementation
tool_code = '''
from typing import ClassVar
from pydantic import Field
from openhands.sdk import Action, Observation
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool

class HelloAction(Action):
    name: str = Field(..., description="Name to greet")

class HelloObservation(Observation):
    greeting: str = Field(..., description="The greeting message")

class HelloExecutor(ToolExecutor[HelloAction, HelloObservation]):
    def __call__(self, action, conversation=None):
        greeting = f"Hello, {action.name}! 👋 This is a custom tool!"
        return HelloObservation.from_text(text=greeting, greeting=greeting)

class HelloTool(ToolDefinition[HelloAction, HelloObservation]):
    name: ClassVar[str] = "hello_tool"
    
    @classmethod
    def create(cls, conv_state=None):
        return [cls(
            description="A simple greeting tool to test custom tool installation",
            action_type=HelloAction,
            observation_type=HelloObservation,
            executor=HelloExecutor(),
        )]

# Auto-register when imported
register_tool("hello_tool", HelloTool)
'''

setup_py = '''
from setuptools import setup, find_packages

setup(
    name="custom_hello_tool",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[],
)
'''

# Upload files to create the package
log("Uploading package files...")

# Upload setup.py
resp = requests.post(
    f"{agent_server}/api/file/write",
    headers={"X-Session-API-Key": session_key},
    json={"path": "/workspace/custom_hello_tool_pkg/setup.py", "content": setup_py}
)
log(f"  setup.py: {resp.status_code}")

# Create package directory
resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": "mkdir -p /workspace/custom_hello_tool_pkg/custom_hello_tool"}
)

# Upload __init__.py (empty)
resp = requests.post(
    f"{agent_server}/api/file/write",
    headers={"X-Session-API-Key": session_key},
    json={"path": "/workspace/custom_hello_tool_pkg/custom_hello_tool/__init__.py", "content": ""}
)

# Upload tool.py
resp = requests.post(
    f"{agent_server}/api/file/write",
    headers={"X-Session-API-Key": session_key},
    json={"path": "/workspace/custom_hello_tool_pkg/custom_hello_tool/tool.py", "content": tool_code}
)
log(f"  tool.py: {resp.status_code}")

# Step 3: Install the package
log("\nInstalling custom tool package...")
resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": "cd /workspace/custom_hello_tool_pkg && pip install -e ."}
)

time.sleep(3)  # Wait for installation

log("Checking installation...")
resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": "pip list | grep custom-hello"}
)

time.sleep(2)

# Step 4: Create conversation with custom tool
log("\nCreating conversation with custom tool...")

payload = {
    "agent": {
        "llm": {
            "model": "gpt-4",
            "api_key": os.getenv("LLM_API_KEY", "placeholder"),
        },
        "tools": [
            {"name": "terminal"},
            {"name": "hello_tool"}  # Our custom tool!
        ],
    },
    "tool_module_qualnames": {
        "terminal": "openhands.tools.terminal.definition",
        "hello_tool": "custom_hello_tool.tool"  # Our installed package!
    },
    "workspace": {"working_dir": "/workspace"},
}

resp = requests.post(
    f"{agent_server}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json=payload
)
log(f"Conversation creation: {resp.status_code}")

if resp.status_code != 200:
    log(f"ERROR: {resp.text}")
    sys.exit(1)

conv_data = resp.json()
conv_id = conv_data.get("id")
log(f"Conversation ID: {conv_id}")

# Step 5: Test using the tool
log("\nTesting custom tool usage...")

resp = requests.post(
    f"{agent_server}/api/conversations/{conv_id}/message",
    headers={"X-Session-API-Key": session_key},
    json={
        "content": "Use the hello_tool to greet 'OpenHands'",
        "event_kind": "MessageEvent"
    }
)

resp = requests.post(
    f"{agent_server}/api/conversations/{conv_id}/run",
    headers={"X-Session-API-Key": session_key},
    json={}
)

log("Waiting for execution...")
time.sleep(8)

# Check events
resp = requests.get(
    f"{agent_server}/api/conversations/{conv_id}/events",
    headers={"X-Session-API-Key": session_key}
)

events = resp.json()
log(f"\nReceived {len(events)} events")

# Look for our custom tool usage
for event in events:
    if event.get("tool_name") == "hello_tool":
        log(f"✅ CUSTOM TOOL USED!")
        log(f"   Action: {event}")
    if "Hello, OpenHands" in str(event):
        log(f"✅ CUSTOM TOOL OUTPUT FOUND!")
        log(f"   {event.get('content', '')[:200]}")

# Cleanup
log("\nCleaning up...")
requests.post(f"{agent_server}/api/end", headers={"X-Session-API-Key": session_key})

log("\n=== EXPERIMENT COMPLETE ===")
