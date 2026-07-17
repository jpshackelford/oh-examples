#!/usr/bin/env python3
"""Detect an idle agent by polling the agent-server's own idle timer.

The agent-server exposes ``GET /server_info``, which reports ``idle_time`` —
seconds since the last activity on the server (file ops, agent steps, ACP
heartbeat, …). This is the *exact* signal ``runtime-api`` polls to decide when a
sandbox is idle enough to pause/reap. This script uses the same signal to detect
when an agent has gone quiet.

Flow (LOCALLY-RUN agent-server in Docker):

    1. Start the agent-server container and wait for GET /health.
    2. Read ``GET /server_info`` for the baseline (``runtime_idle_timeout_seconds``
       is the platform's own reap threshold).
    3. Create a conversation with a runnable ``initial_message``.
    4. Poll ``GET /server_info`` every few seconds. ``idle_time`` drops while the
       agent works and climbs once it stops. When it crosses our threshold, we
       declare the agent idle (done).
    5. Tear the container down.

``idle_time`` vs. ``execution_status``: idle_time is a coarse "has anything
happened lately?" heartbeat — it does NOT distinguish finished / error / stuck,
and it is what the platform itself uses for reaping. For an authoritative,
per-conversation terminal signal use ``execution_status`` (see
``../websocket-events`` for the push version and ``../react-to-state-webhooks``
for the webhook version). idle_time shines when you just want "the workspace has
gone quiet" without subscribing to any conversation.

Prerequisites: Docker running. Install deps::

    pip install requests

Configure the LLM (same shape as the rest of the repo)::

    export LLM_API_KEY=...                 # required
    export LLM_MODEL=litellm_proxy/...     # required
    export LLM_BASE_URL=https://...        # optional (provider default if unset)
    python idle_poll.py

Env vars: LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, SESSION_API_KEY,
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
        "--llm-api-key",
        default=os.environ.get("LLM_API_KEY"),
        help="LLM API key (default: $LLM_API_KEY).",
    )
    p.add_argument(
        "--llm-model",
        default=os.environ.get("LLM_MODEL"),
        help="LLM model, e.g. litellm_proxy/... (default: $LLM_MODEL).",
    )
    p.add_argument(
        "--llm-base-url",
        default=os.environ.get("LLM_BASE_URL"),
        help="Optional LLM base URL (default: $LLM_BASE_URL).",
    )
    p.add_argument(
        "--session-key",
        default=os.environ.get("SESSION_API_KEY", "local-demo-key"),
        help="Session API key the server requires (default: $SESSION_API_KEY "
        "or local-demo-key).",
    )
    p.add_argument(
        "--image",
        default=os.environ.get(
            "OH_AGENT_SERVER_IMAGE",
            "ghcr.io/openhands/agent-server:latest-python",
        ),
        help="agent-server Docker image (default: $OH_AGENT_SERVER_IMAGE).",
    )
    p.add_argument(
        "--server-port",
        type=int,
        default=int(os.environ.get("OH_SERVER_PORT", "8000")),
        help="Host port to map the agent-server onto (default: 8000).",
    )
    p.add_argument(
        "--container-name",
        default="oh-idle-demo",
        help="Name for the agent-server container (default: oh-idle-demo).",
    )
    p.add_argument(
        "--message",
        default="Say hello in one short sentence, then stop.",
        help="Initial message for the conversation.",
    )
    p.add_argument(
        "--health-timeout",
        type=int,
        default=90,
        help="Seconds to wait for GET /health (default: 90).",
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
        help="Leave the container running at the end instead of removing it.",
    )
    return p.parse_args()


def start_container(args: argparse.Namespace) -> None:
    """docker run the agent-server with a session key set via env var."""
    subprocess.run(
        ["docker", "rm", "-f", args.container_name],
        check=False,
        capture_output=True,
    )
    cmd = [
        "docker",
        "run",
        "-d",
        "--name",
        args.container_name,
        "-p",
        f"{args.server_port}:8000",
        # SESSION_API_KEY seeds both the accepted-key list and the secret key
        # (config.py _default_session_api_keys / _default_secret_key).
        "-e",
        f"SESSION_API_KEY={args.session_key}",
        args.image,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(f"container: {result.stdout.strip()[:12]}")


def get_server_info(base: str, headers: dict) -> dict:
    """GET /server_info -> dict with idle_time, uptime, and thresholds."""
    r = requests.get(f"{base}/server_info", headers=headers, timeout=5)
    r.raise_for_status()
    return r.json()


def wait_for_health(base: str, headers: dict, timeout: int) -> None:
    """Poll GET /health until ok (server readiness)."""
    deadline = time.monotonic() + timeout
    while True:
        try:
            r = requests.get(f"{base}/health", headers=headers, timeout=5)
            if r.ok and r.json().get("status") == "ok":
                print("health: ok")
                return
        except requests.RequestException:
            pass
        if time.monotonic() > deadline:
            raise TimeoutError(f"agent-server /health not ok within {timeout}s")
        time.sleep(2)


def create_conversation(
    base: str, headers: dict, model: str, base_url: str | None, key: str, msg: str
) -> str:
    """POST /api/conversations with a runnable initial_message. Returns id."""
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
    r = requests.post(f"{base}/api/conversations", headers=headers, json=body)
    r.raise_for_status()
    cid = r.json()["id"]
    print(f"conversation: {cid}")
    return cid


def watch_idle(base: str, headers: dict, args: argparse.Namespace) -> bool:
    """Poll /server_info.idle_time until it crosses the threshold.

    Returns True if the idle threshold was reached, False on timeout.
    """
    deadline = time.monotonic() + args.watch_timeout
    print(
        f"\npolling /server_info.idle_time every {args.poll_interval}s; "
        f"declaring idle at > {args.idle_threshold}s\n"
    )
    while time.monotonic() < deadline:
        info = get_server_info(base, headers)
        idle = info.get("idle_time", 0)
        print(f"  idle_time={idle:>5}s  uptime={info.get('uptime')}s")
        if idle > args.idle_threshold:
            return True
        time.sleep(args.poll_interval)
    return False


def teardown(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
    print(f"removed container {name}")


def main() -> None:
    args = parse_args()
    if not args.llm_api_key or not args.llm_model:
        sys.exit("error: set --llm-api-key/--llm-model or $LLM_API_KEY/$LLM_MODEL")

    base = f"http://localhost:{args.server_port}"
    headers = {"X-Session-API-Key": args.session_key}

    try:
        start_container(args)
        wait_for_health(base, headers, args.health_timeout)

        baseline = get_server_info(base, headers)
        print(
            "baseline /server_info: "
            f"idle_time={baseline.get('idle_time')}s "
            f"runtime_idle_timeout_seconds={baseline.get('runtime_idle_timeout_seconds')}"
        )

        create_conversation(
            base,
            headers,
            args.llm_model,
            args.llm_base_url,
            args.llm_api_key,
            args.message,
        )

        if watch_idle(base, headers, args):
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
            print(f"left container {args.container_name} running (--keep)")
        else:
            teardown(args.container_name)


if __name__ == "__main__":
    main()
