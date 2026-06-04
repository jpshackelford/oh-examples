#!/usr/bin/env python3
"""Create a sandbox, wait until ready, ls /workspace, show agent-server proc.

Demonstrates starting an OpenHands sandbox via the Cloud API without
creating a conversation, then talking directly to the sandbox's
agent-server REST API.

Usage:
    export OH_API_KEY=...        # Cloud API key
    python sandbox_demo.py
"""
import os
import time

import requests


CLOUD = "https://app.all-hands.dev"
HEADERS = {"X-Session-API-Key": os.environ["OH_API_KEY"]}


def main() -> None:
    # 1. Start sandbox (no conversation).
    sb = requests.post(f"{CLOUD}/api/v1/sandboxes", headers=HEADERS).json()
    sid = sb["id"]
    print("sandbox:", sid)

    # 2. Poll batch-get-by-id until RUNNING.
    while sb["status"] != "RUNNING":
        time.sleep(3)
        sb = requests.get(
            f"{CLOUD}/api/v1/sandboxes",
            headers=HEADERS,
            params={"id": sid},
        ).json()[0]
        print("  status:", sb["status"])

    # 3. Locate the agent-server URL + per-sandbox session key.
    agent_url = next(
        u["url"] for u in sb["exposed_urls"] if u["name"] == "AGENT_SERVER"
    )
    sess = {"X-Session-API-Key": sb["session_api_key"]}
    print("agent:", agent_url)

    # 4. Exec commands via /api/bash/execute_bash_command.
    def sh(cmd: str) -> str:
        r = requests.post(
            f"{agent_url}/api/bash/execute_bash_command",
            headers=sess,
            json={"command": cmd, "timeout": 30},
        ).json()
        return (r.get("stdout") or "") + (r.get("stderr") or "")

    print("\n=== ls -la /workspace ===")
    print(sh("ls -la /workspace"))
    print("=== agent-server process ===")
    print(sh(
        "ps -ef | grep -E 'openhands.agent_server|openhands-agent-server' "
        "| grep -v grep"
    ))


if __name__ == "__main__":
    main()
