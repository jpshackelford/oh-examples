#!/usr/bin/env python3
"""Brief version: create sandbox, wait, ls /workspace, show agent-server proc.

Favors brevity over error handling and nice output so the API shape is
easy to scan. See sandbox_demo.py for the more idiomatic version.

    export OH_API_KEY=...        # Cloud API key
    python sandbox_demo_brief.py
"""

import os
import time

import requests


CLOUD = os.environ.get("OH_API_BASE", "https://app.all-hands.dev")
HEADERS = {"X-Session-API-Key": os.environ["OH_API_KEY"]}

# 1. Start sandbox
sb = requests.post(f"{CLOUD}/api/v1/sandboxes", headers=HEADERS).json()
sid = sb["id"]
print("sandbox:", sid)

# 2. Poll until RUNNING (batch-get-by-id), max ~3 minutes
for _ in range(60):
    if sb["status"] == "RUNNING":
        break
    time.sleep(3)
    sb = requests.get(
        f"{CLOUD}/api/v1/sandboxes", headers=HEADERS, params={"id": sid}
    ).json()[0]
    print("  status:", sb["status"])
else:
    raise TimeoutError(f"sandbox {sid} never reached RUNNING")

# 3. Locate the agent-server URL + per-sandbox session key
agent_url = next(u["url"] for u in sb["exposed_urls"] if u["name"] == "AGENT_SERVER")
sess = {"X-Session-API-Key": sb["session_api_key"]}
print("agent:", agent_url)


# 4. Exec commands via /api/bash/execute_bash_command
def sh(cmd):
    r = requests.post(
        f"{agent_url}/api/bash/execute_bash_command",
        headers=sess,
        json={"command": cmd, "timeout": 30},
    ).json()
    return (r.get("stdout") or "") + (r.get("stderr") or "")


print("\n=== ls -la /workspace ===")
print(sh("ls -la /workspace"))
print("=== agent-server process ===")
proc = "ps -ef | grep -E 'openhands.agent_server|openhands-agent-server' | grep -v grep"
print(sh(proc))
