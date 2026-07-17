#!/usr/bin/env python3
"""Detect an idle agent by polling the agent-server's own idle timer (Cloud).

The agent-server exposes ``GET /server_info``, which reports ``idle_time`` —
seconds since the last activity on the server (file ops, agent steps, ACP
heartbeat, …). This is the *exact* signal ``runtime-api`` polls to decide when a
sandbox is idle enough to pause/reap, and on Cloud the response also carries
``runtime_idle_timeout_seconds`` — the platform's real reap threshold. This
script uses the same signal to detect when an agent has gone quiet.

Cloud flow (the default):

    1. Start a Cloud sandbox (POST /api/v1/sandboxes) and wait for RUNNING.
    2. Read ``GET <agent>/server_info`` for the baseline, including the
       platform's own ``runtime_idle_timeout_seconds``.
    3. Attach a conversation (POST /api/v1/app-conversations) — no LLM key
       needed; the Cloud layer injects your account's credentials.
    4. Poll ``GET <agent>/server_info`` every few seconds. ``idle_time`` drops
       while the agent works and climbs once it stops. When it crosses our
       (small, demo) threshold, we declare the agent idle.
    5. Delete the sandbox.

``idle_time`` vs. ``execution_status``: idle_time is a coarse "has anything
happened lately?" heartbeat — it does NOT distinguish finished / error / stuck,
and it is what the platform itself uses for reaping. For an authoritative,
per-conversation terminal signal use ``execution_status`` (see
``../watch-terminal-state`` for the push version over the WebSocket, and the
proposed react-to-state-webhooks example,
https://github.com/jpshackelford/oh-examples/pull/22, for the webhook version).
idle_time shines when you just want "the workspace has gone quiet" without
subscribing to any conversation.

    export OH_API_KEY=...            # Cloud API key (required)
    pip install requests
    python idle_poll.py

Local fallback (no Cloud account): start an agent-server in Docker yourself and
point this script at it — see ``--local`` below.

Env vars: OH_API_KEY, OH_API_BASE, SANDBOX_SPEC_ID, POLL_TIMEOUT, and (for the
local fallback) LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, SESSION_API_KEY,
OH_AGENT_SERVER_IMAGE, OH_SERVER_PORT.
"""

import argparse
import os
import subprocess
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
        "--message",
        default="Say hello in one short sentence, then stop.",
        help="Initial user message for the conversation.",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=int(os.environ.get("POLL_TIMEOUT", "180")),
        help="Seconds to wait for the sandbox / start task (default: 180).",
    )
    p.add_argument(
        "--idle-threshold",
        type=float,
        default=15.0,
        help="Declare the agent idle after idle_time exceeds this many seconds. "
        "Kept small for a snappy demo; the platform's own reap threshold "
        "(runtime_idle_timeout_seconds) is usually 1200-1800s (default: 15).",
    )
    p.add_argument(
        "--poll-interval",
        type=float,
        default=3.0,
        help="Seconds between /server_info polls (default: 3).",
    )
    p.add_argument(
        "--watch-timeout",
        type=int,
        default=180,
        help="Max seconds to watch before giving up (default: 180).",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Leave the sandbox (or local container) running at the end.",
    )

    # --- Local fallback (no Cloud account) ---
    local = p.add_argument_group(
        "local fallback", "Run against an agent-server you start in Docker."
    )
    local.add_argument(
        "--local",
        action="store_true",
        help="Use a local Docker agent-server instead of a Cloud sandbox.",
    )
    local.add_argument(
        "--llm-api-key",
        default=os.environ.get("LLM_API_KEY"),
        help="[--local] LLM API key (default: $LLM_API_KEY).",
    )
    local.add_argument(
        "--llm-model",
        default=os.environ.get("LLM_MODEL"),
        help="[--local] LLM model, e.g. litellm_proxy/... (default: $LLM_MODEL).",
    )
    local.add_argument(
        "--llm-base-url",
        default=os.environ.get("LLM_BASE_URL"),
        help="[--local] Optional LLM base URL (default: $LLM_BASE_URL).",
    )
    local.add_argument(
        "--session-key",
        default=os.environ.get("SESSION_API_KEY", "local-demo-key"),
        help="[--local] Session key the container requires (default: local-demo-key).",
    )
    local.add_argument(
        "--image",
        default=os.environ.get(
            "OH_AGENT_SERVER_IMAGE",
            "ghcr.io/openhands/agent-server:latest-python",
        ),
        help="[--local] agent-server Docker image.",
    )
    local.add_argument(
        "--server-port",
        type=int,
        default=int(os.environ.get("OH_SERVER_PORT", "8000")),
        help="[--local] Host port to map the agent-server onto (default: 8000).",
    )
    local.add_argument(
        "--container-name",
        default="oh-idle-demo",
        help="[--local] Name for the agent-server container.",
    )
    return p.parse_args()


def get_server_info(agent_url: str, headers: dict) -> dict:
    """GET /server_info -> dict with idle_time, uptime, and thresholds."""
    r = requests.get(f"{agent_url}/server_info", headers=headers, timeout=10)
    r.raise_for_status()
    return r.json()


def watch_idle(agent_url: str, headers: dict, args: argparse.Namespace) -> bool:
    """Poll /server_info.idle_time until it crosses the threshold.

    Returns True if the idle threshold was reached, False on timeout.
    """
    deadline = time.monotonic() + args.watch_timeout
    print(
        f"\npolling /server_info.idle_time every {args.poll_interval}s; "
        f"declaring idle at > {args.idle_threshold}s\n"
    )
    while time.monotonic() < deadline:
        info = get_server_info(agent_url, headers)
        idle = info.get("idle_time", 0)
        print(f"  idle_time={idle:>5}s  uptime={info.get('uptime')}s")
        if idle > args.idle_threshold:
            return True
        time.sleep(args.poll_interval)
    return False


# --------------------------------------------------------------------------- #
# Cloud path
# --------------------------------------------------------------------------- #
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
            f"{base_url}/api/v1/sandboxes", headers=headers, params={"id": sandbox_id}
        )
        resp.raise_for_status()
        results = resp.json()
        if not results or results[0] is None:
            raise ValueError(f"Sandbox {sandbox_id} not found")
        sb = results[0]
        print("  sandbox status:", sb["status"])
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


def attach_conversation(
    base_url: str, headers: dict, sandbox_id: str, message: str, timeout: int
) -> str:
    """POST /api/v1/app-conversations with sandbox_id; poll start-task for its id."""
    payload = {
        "sandbox_id": sandbox_id,
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": message}],
        },
        "title": "server-info-idle",
    }
    resp = requests.post(
        f"{base_url}/api/v1/app-conversations", headers=headers, json=payload
    )
    resp.raise_for_status()
    task = resp.json()
    conv_id = task.get("app_conversation_id")
    task_id = task["id"]

    deadline = time.monotonic() + timeout
    while not conv_id:
        if time.monotonic() > deadline:
            raise TimeoutError("start task did not yield a conversation id in time")
        time.sleep(2)
        resp = requests.get(
            f"{base_url}/api/v1/app-conversations/start-tasks",
            headers=headers,
            params={"ids": task_id},
        )
        resp.raise_for_status()
        items = resp.json()
        item = items[0] if isinstance(items, list) else items
        print("  start-task status:", item.get("status"))
        conv_id = item.get("app_conversation_id")
    return conv_id


def delete_sandbox(base_url: str, headers: dict, sandbox_id: str) -> None:
    requests.delete(
        f"{base_url}/api/v1/sandboxes/{sandbox_id}",
        headers=headers,
        params={"sandbox_id": sandbox_id},
    )


def run_cloud(args: argparse.Namespace) -> None:
    if not args.api_key:
        sys.exit("error: set --api-key or the OH_API_KEY environment variable")
    headers = {"X-Session-API-Key": args.api_key}

    sb = start_sandbox(args.base_url, headers, args.sandbox_spec_id)
    sid = sb["id"]
    print("sandbox:", sid)
    sb = wait_until_running(args.base_url, headers, sid, args.poll_timeout)

    try:
        agent_url = agent_server_url(sb)
        agent_headers = {"X-Session-API-Key": sb["session_api_key"]}
        print("agent:", agent_url)

        baseline = get_server_info(agent_url, agent_headers)
        print(
            "baseline /server_info: "
            f"idle_time={baseline.get('idle_time')}s "
            f"runtime_idle_timeout_seconds={baseline.get('runtime_idle_timeout_seconds')}"
        )

        print("\n=== attaching conversation (start-task poll) ===")
        conv_id = attach_conversation(
            args.base_url, headers, sid, args.message, args.poll_timeout
        )
        print("conversation:", conv_id)

        if watch_idle(agent_url, agent_headers, args):
            print(
                f"\nagent idle: idle_time exceeded {args.idle_threshold}s "
                "— the workspace has gone quiet."
            )
            print(
                "(this is the same signal runtime-api uses to reap sandboxes; "
                "for a per-conversation terminal state use execution_status)"
            )
        else:
            print(f"\nidle threshold not reached within {args.watch_timeout}s")
    finally:
        if args.keep:
            delete_url = f"{args.base_url}/api/v1/sandboxes/{sid}?sandbox_id={sid}"
            print(
                "\nSandbox left running. Delete it with:\n"
                f'  curl -X DELETE "{delete_url}" \\\n'
                '       -H "X-Session-API-Key: $OH_API_KEY"'
            )
        else:
            print("\nCleaning up sandbox…")
            delete_sandbox(args.base_url, headers, sid)


# --------------------------------------------------------------------------- #
# Local fallback path
# --------------------------------------------------------------------------- #
def start_container(args: argparse.Namespace) -> None:
    """docker run the agent-server with a session key set via env var."""
    subprocess.run(
        ["docker", "rm", "-f", args.container_name], check=False, capture_output=True
    )
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        args.container_name,
        "-p",
        f"{args.server_port}:8000",
        "-e",
        f"SESSION_API_KEY={args.session_key}",
        args.image,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(f"container: {result.stdout.strip()[:12]}")


def wait_for_health(agent_url: str, headers: dict, timeout: int) -> None:
    """Poll GET /health until ok (server readiness)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            r = requests.get(f"{agent_url}/health", headers=headers, timeout=5)
            if r.ok and r.json().get("status") == "ok":
                print("health: ok")
                return
        except requests.RequestException:
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(f"agent-server /health not ok within {timeout}s")
        time.sleep(2)


def create_conversation_local(
    agent_url: str, headers: dict, model: str, base_url: str | None, key: str, msg: str
) -> str:
    """POST /api/conversations directly on the agent-server. Returns id."""
    llm = {"usage_id": "agent", "model": model, "api_key": key}
    if base_url:
        llm["base_url"] = base_url
    body = {
        "agent": {"llm": llm},
        "workspace": {"kind": "LocalWorkspace", "working_dir": "/workspace/project"},
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": msg}],
            "run": True,
        },
        "max_iterations": 10,
    }
    r = requests.post(f"{agent_url}/api/conversations", headers=headers, json=body)
    r.raise_for_status()
    cid = r.json()["id"]
    print(f"conversation: {cid}")
    return cid


def run_local(args: argparse.Namespace) -> None:
    if not args.llm_api_key or not args.llm_model:
        sys.exit(
            "error (--local): set --llm-api-key/--llm-model or $LLM_API_KEY/$LLM_MODEL"
        )
    agent_url = f"http://localhost:{args.server_port}"
    headers = {"X-Session-API-Key": args.session_key}

    try:
        start_container(args)
        wait_for_health(agent_url, headers, args.poll_timeout)

        baseline = get_server_info(agent_url, headers)
        print(
            "baseline /server_info: "
            f"idle_time={baseline.get('idle_time')}s "
            f"runtime_idle_timeout_seconds={baseline.get('runtime_idle_timeout_seconds')}"
            "  # null locally: there is no platform reaper"
        )

        create_conversation_local(
            agent_url,
            headers,
            args.llm_model,
            args.llm_base_url,
            args.llm_api_key,
            args.message,
        )

        if watch_idle(agent_url, headers, args):
            print(
                f"\nagent idle: idle_time exceeded {args.idle_threshold}s "
                "— the workspace has gone quiet."
            )
        else:
            print(f"\nidle threshold not reached within {args.watch_timeout}s")
    finally:
        if args.keep:
            print(f"left container {args.container_name} running (--keep)")
        else:
            subprocess.run(
                ["docker", "rm", "-f", args.container_name],
                check=False,
                capture_output=True,
            )
            print(f"removed container {args.container_name}")


def main() -> None:
    args = parse_args()
    if args.local:
        run_local(args)
    else:
        run_cloud(args)


if __name__ == "__main__":
    main()
