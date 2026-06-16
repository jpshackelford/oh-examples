#!/usr/bin/env python3
"""Create a sandbox, wait until ready, ls /workspace, show agent-server proc.

Demonstrates starting an OpenHands sandbox via the Cloud API *without*
creating a conversation, then talking directly to the sandbox's
agent-server REST API.

Everything is configurable via flags or environment variables so you can
drop this script into your own tooling unchanged:

    export OH_API_KEY=...            # Cloud API key (required)
    python sandbox_demo.py

    # or override anything:
    python sandbox_demo.py \
        --base-url https://app.all-hands.dev \
        --sandbox-spec-id <spec> \
        --poll-timeout 240

Env vars: OH_API_KEY, OH_API_BASE, SANDBOX_SPEC_ID.
"""

import argparse
import os
import sys
import time

import requests


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--api-key",
        default=os.environ.get("OH_API_KEY"),
        help="Cloud API key (default: $OH_API_KEY).",
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("OH_API_BASE", "https://app.all-hands.dev"),
        help="Cloud app server base URL (default: $OH_API_BASE or app.all-hands.dev).",
    )
    p.add_argument(
        "--sandbox-spec-id",
        default=os.environ.get("SANDBOX_SPEC_ID"),
        help="Optional runtime image spec id (default: $SANDBOX_SPEC_ID).",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=int(os.environ.get("POLL_TIMEOUT", "180")),
        help="Seconds to wait for the sandbox to reach RUNNING (default: 180).",
    )
    return p.parse_args()


def start_sandbox(base_url: str, headers: dict, spec_id: str | None) -> dict:
    """POST /api/v1/sandboxes -> SandboxInfo (status is initially STARTING)."""
    params = {"sandbox_spec_id": spec_id} if spec_id else None
    resp = requests.post(f"{base_url}/api/v1/sandboxes", headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def wait_until_running(
    base_url: str, headers: dict, sandbox_id: str, timeout: int
) -> dict:
    """Poll the batch-get-by-id endpoint until status == RUNNING."""
    deadline = time.monotonic() + timeout
    while True:
        resp = requests.get(
            f"{base_url}/api/v1/sandboxes",
            headers=headers,
            params={"id": sandbox_id},
        )
        resp.raise_for_status()
        results = resp.json()
        if not results or results[0] is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")
        sb = results[0]
        print("  status:", sb["status"])
        if sb["status"] == "RUNNING":
            return sb
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Sandbox {sandbox_id} did not reach RUNNING within {timeout}s "
                f"(last status: {sb['status']})"
            )
        time.sleep(3)


def agent_server_url(sandbox: dict) -> str:
    """Pick the AGENT_SERVER entry from the sandbox's exposed_urls."""
    url = next(
        (u["url"] for u in sandbox["exposed_urls"] if u["name"] == "AGENT_SERVER"),
        None,
    )
    if not url:
        raise ValueError(f"AGENT_SERVER URL not found in sandbox {sandbox['id']}")
    return url


def run_command(agent_url: str, session: dict, cmd: str, timeout: int = 30) -> str:
    """POST /api/bash/execute_bash_command on the agent server and return output."""
    resp = requests.post(
        f"{agent_url}/api/bash/execute_bash_command",
        headers=session,
        json={"command": cmd, "timeout": timeout},
    )
    resp.raise_for_status()
    result = resp.json()
    stdout = result.get("stdout") or ""
    stderr = result.get("stderr") or ""
    if stderr:
        return f"{stdout}\n[stderr]:\n{stderr}"
    return stdout


def main() -> None:
    args = parse_args()
    if not args.api_key:
        sys.exit("error: set --api-key or the OH_API_KEY environment variable")
    headers = {"X-Session-API-Key": args.api_key}

    # 1. Start sandbox (no conversation).
    sb = start_sandbox(args.base_url, headers, args.sandbox_spec_id)
    sid = sb["id"]
    print("sandbox:", sid)

    # 2. Poll batch-get-by-id until RUNNING (bounded by --poll-timeout).
    sb = wait_until_running(args.base_url, headers, sid, args.poll_timeout)

    # 3. Locate the agent-server URL + per-sandbox session key.
    agent_url = agent_server_url(sb)
    session = {"X-Session-API-Key": sb["session_api_key"]}
    print("agent:", agent_url)

    # 4. Exec commands via /api/bash/execute_bash_command.
    print("\n=== ls -la /workspace ===")
    print(run_command(agent_url, session, "ls -la /workspace"))
    print("=== agent-server process ===")
    print(
        run_command(
            agent_url,
            session,
            "ps -ef | grep -E 'openhands.agent_server|openhands-agent-server' "
            "| grep -v grep",
        )
    )

    delete_url = f"{args.base_url}/api/v1/sandboxes/{sid}?sandbox_id={sid}"
    print(
        "\nSandbox left running. Delete it with:\n"
        f'  curl -X DELETE "{delete_url}" \\\n'
        '       -H "X-Session-API-Key: $OH_API_KEY"'
    )


if __name__ == "__main__":
    main()
