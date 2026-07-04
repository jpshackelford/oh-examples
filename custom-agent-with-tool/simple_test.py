#!/usr/bin/env python3
"""Simple test: Install custom tool package and use it"""

import os
import sys
import time
import requests

api_key = os.getenv("OH_API_KEY")
if not api_key:
    print("ERROR: OH_API_KEY not set")
    sys.exit(1)

# Use the start-sandbox example approach
print("Creating sandbox via start-sandbox endpoint...")
resp = requests.post(
    "https://app.all-hands.dev/api/v1/sandboxes",
    headers={"Authorization": f"Bearer {api_key}"},
    json={}
)

if resp.status_code != 200:
    print(f"ERROR creating sandbox: {resp.status_code} - {resp.text}")
    sys.exit(1)

data = resp.json()
sandbox_id = data["sandbox_id"]
agent_server = data["agent_server_url"]
session_key = data["session_api_key"]

print(f"✅ Sandbox: {sandbox_id}")
print(f"✅ Agent-server: {agent_server}")

# Create a minimal custom tool package structure via bash
print("\n📦 Creating custom tool package...")

setup_script = """
mkdir -p /workspace/hello_tool_pkg/hello_tool
cat > /workspace/hello_tool_pkg/setup.py << 'SETUP'
from setuptools import setup, find_packages
setup(
    name="hello-tool",
    version="0.1.0",
    packages=find_packages(),
)
SETUP

cat > /workspace/hello_tool_pkg/hello_tool/__init__.py << 'INIT'
# Empty init
INIT

cat > /workspace/hello_tool_pkg/hello_tool/tool.py << 'TOOL'
from typing import ClassVar
from pydantic import Field
from openhands.sdk import Action, Observation
from openhands.sdk.tool import ToolDefinition, ToolExecutor, register_tool

class HelloAction(Action):
    name: str = Field(..., description="Name to greet")

class HelloObservation(Observation):
    greeting: str = Field(..., description="Greeting message")

class HelloExecutor(ToolExecutor[HelloAction, HelloObservation]):
    def __call__(self, action, conversation=None):
        msg = f"Hello {action.name}! Custom tool works! 🎉"
        return HelloObservation.from_text(text=msg, greeting=msg)

class HelloTool(ToolDefinition[HelloAction, HelloObservation]):
    name: ClassVar[str] = "hello_tool"
    
    @classmethod
    def create(cls, conv_state=None):
        return [cls(
            description="Simple greeting tool",
            action_type=HelloAction,
            observation_type=HelloObservation,
            executor=HelloExecutor(),
        )]

register_tool("hello_tool", HelloTool)
TOOL

echo "Package structure created"
""".strip()

resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": setup_script}
)
print(f"Setup script: {resp.status_code}")
time.sleep(2)

# Install the package
print("📦 Installing custom tool package...")
resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": "cd /workspace/hello_tool_pkg && pip install -e ."}
)
print(f"Install: {resp.status_code}")
time.sleep(3)

# Verify installation
resp = requests.post(
    f"{agent_server}/api/bash/execute_bash_command",
    headers={"X-Session-API-Key": session_key},
    json={"command": "pip list | grep hello-tool && python -c 'import hello_tool.tool; print(\"Import successful!\")' "}
)
print(f"Verify: {resp.status_code}")
time.sleep(2)

# Create conversation with custom tool
print("\n🚀 Creating conversation with custom tool...")

payload = {
    "agent": {
        "llm": {"model": "gpt-4", "api_key": os.getenv("LLM_API_KEY", "test")},
        "tools": [{"name": "hello_tool"}]
    },
    "tool_module_qualnames": {
        "hello_tool": "hello_tool.tool"
    },
    "workspace": {"working_dir": "/workspace"}
}

resp = requests.post(
    f"{agent_server}/api/conversations",
    headers={"X-Session-API-Key": session_key},
    json=payload
)

print(f"Conversation creation: {resp.status_code}")
if resp.status_code != 200:
    print(f"ERROR: {resp.text}")
    sys.exit(1)

conv_id = resp.json()["id"]
print(f"✅ Conversation: {conv_id}")

# Send message using the tool
print("\n📝 Testing custom tool...")
resp = requests.post(
    f"{agent_server}/api/conversations/{conv_id}/message",
    headers={"X-Session-API-Key": session_key},
    json={"content": "Use hello_tool to greet 'World'", "event_kind": "MessageEvent"}
)

resp = requests.post(
    f"{agent_server}/api/conversations/{conv_id}/run",
    headers={"X-Session-API-Key": session_key},
    json={}
)
print("Waiting for execution...")
time.sleep(10)

# Check results
resp = requests.get(
    f"{agent_server}/api/conversations/{conv_id}/events",
    headers={"X-Session-API-Key": session_key}
)

events = resp.json()
print(f"\n📊 Received {len(events)} events")

found_tool = False
found_output = False

for event in events:
    if event.get("tool_name") == "hello_tool":
        found_tool = True
        print(f"✅ CUSTOM TOOL CALLED: {event.get('action', {})}")
    
    if "Hello World" in str(event) and "Custom tool works" in str(event):
        found_output = True
        print(f"✅ CUSTOM TOOL OUTPUT: {event.get('content', '')[:200]}")

if found_tool and found_output:
    print("\n🎉 SUCCESS! Custom tool worked via tool_module_qualnames!")
else:
    print(f"\n⚠️  Tool called: {found_tool}, Output found: {found_output}")

# Cleanup
requests.delete(
    f"https://app.all-hands.dev/api/v1/sandboxes/{sandbox_id}",
    headers={"Authorization": f"Bearer {api_key}"}
)
print("\n✅ Cleanup complete")
