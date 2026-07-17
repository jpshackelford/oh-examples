#!/usr/bin/env python3
"""React to conversation state changes via agent-server OUTBOUND WEBHOOKS.

Event-driven, no polling. This script drives a LOCALLY-RUN agent-server (in
Docker) end-to-end:

    1. Write a startup config JSON that registers a webhook pointing back at a
       receiver running on your host (see ``receiver.py``). The container
       reaches the host via ``host.docker.internal``.
    2. Start the agent-server container from the software-agent-sdk image and
       wait for GET /health to return ok.
    3. Create a conversation (POST /api/conversations) with a small
       ``initial_message`` and run it.
    4. The agent-server POSTs state changes to ``{base_url}/conversations`` and
       batched events to ``{base_url}/events/{id}``. The receiver prints them.
       This script NEVER polls conversation state — the only signal is the
       webhook traffic arriving at the receiver.
    5. Tear the container down.

This example is LOCAL-ONLY. OpenHands Cloud sandboxes run with
``deferred_init=False``: ``POST /api/init`` returns 404 and there is no way to
inject webhook config, so outbound webhooks cannot be registered on Cloud. For
Cloud, consume conversation state over the WebSocket instead.

Prerequisites: Docker running, and ``receiver.py`` already listening (start it
first in another terminal). Everything is configurable via flags / env vars:

    export LLM_API_KEY=...                 # required
    export LLM_MODEL=litellm_proxy/...     # required
    export LLM_BASE_URL=https://...        # optional (provider default if unset)
    python receiver.py &                   # in another terminal
    python run_demo.py

Env vars: LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, SESSION_API_KEY,
OH_AGENT_SERVER_IMAGE, OH_SERVER_PORT, RECEIVER_HOST, RECEIVER_PORT.
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
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
        help="Session API key the server requires and echoes to the webhook "
        "as X-Session-API-Key (default: $SESSION_API_KEY or local-demo-key).",
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
        "--receiver-host",
        default=os.environ.get("RECEIVER_HOST", "host.docker.internal"),
        help="Hostname the CONTAINER uses to reach the receiver "
        "(default: host.docker.internal).",
    )
    p.add_argument(
        "--receiver-port",
        type=int,
        default=int(os.environ.get("RECEIVER_PORT", "8080")),
        help="Port the receiver listens on (default: 8080).",
    )
    p.add_argument(
        "--container-name",
        default="oh-webhook-demo",
        help="Name for the agent-server container (default: oh-webhook-demo).",
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
        "--observe-seconds",
        type=int,
        default=20,
        help="Seconds to let webhook traffic flow before teardown (default: 20).",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Leave the container running at the end instead of removing it.",
    )
    return p.parse_args()


def write_config(path: str, base_url: str, session_key: str) -> None:
    """Write the agent-server startup config with a single webhook spec.

    ``event_buffer_size=1`` and a short ``flush_delay`` make the demo lively:
    events are forwarded almost immediately instead of being batched.
    """
    config = {
        "session_api_keys": [session_key],
        "webhooks": [
            {
                "base_url": base_url,
                "event_buffer_size": 1,
                "flush_delay": 1.0,
            }
        ],
    }
    with open(path, "w") as f:
        json.dump(config, f, indent=2)


def start_container(args: argparse.Namespace, config_path: str) -> None:
    """docker run the agent-server, mounting the config at its default path."""
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
        # host-gateway makes host.docker.internal resolve on Linux too; it is
        # already provided by Docker Desktop on macOS/Windows.
        "--add-host",
        "host.docker.internal:host-gateway",
        "-p",
        f"{args.server_port}:8000",
        "-v",
        f"{config_path}:/workspace/openhands_agent_server_config.json:ro",
        args.image,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(f"container: {result.stdout.strip()[:12]}")


def wait_for_health(base: str, headers: dict, timeout: int) -> None:
    """Poll GET /health until it returns ok (this is server, not convo, state)."""
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


def create_and_run(
    base: str, headers: dict, model: str, base_url: str | None, key: str, msg: str
) -> str:
    """POST /api/conversations then /run. Returns the conversation id."""
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

    # A conversation created with a runnable initial_message starts on its own,
    # so an explicit /run may return 409 ("already running") — that is benign.
    run = requests.post(f"{base}/api/conversations/{cid}/run", headers=headers)
    if run.status_code not in (200, 409):
        run.raise_for_status()
    print(f"run: {run.status_code} (409 = already running, expected)")
    return cid


def teardown(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
    print(f"removed container {name}")


def main() -> None:
    args = parse_args()
    if not args.llm_api_key or not args.llm_model:
        sys.exit("error: set --llm-api-key/--llm-model or $LLM_API_KEY/$LLM_MODEL")

    base = f"http://localhost:{args.server_port}"
    headers = {"X-Session-API-Key": args.session_key}
    webhook_base = f"http://{args.receiver_host}:{args.receiver_port}"
    print(
        f"webhook target (from container): {webhook_base}\n"
        f"  -> POST {webhook_base}/conversations (state changes)\n"
        f"  -> POST {webhook_base}/events/{{id}} (batched events)\n"
        "make sure receiver.py is listening on "
        f"port {args.receiver_port} on this host.\n"
    )

    fd, config_path = tempfile.mkstemp(prefix="oh_webhook_", suffix=".json")
    os.close(fd)
    # World-readable so the in-container 'openhands' user can read the mount.
    os.chmod(config_path, 0o644)
    write_config(config_path, webhook_base, args.session_key)

    try:
        start_container(args, config_path)
        wait_for_health(base, headers, args.health_timeout)
        create_and_run(
            base,
            headers,
            args.llm_model,
            args.llm_base_url,
            args.llm_api_key,
            args.message,
        )
        print(
            f"\nwatching webhooks for {args.observe_seconds}s "
            "(see the receiver terminal for callbacks)..."
        )
        time.sleep(args.observe_seconds)
    finally:
        os.unlink(config_path)
        if args.keep:
            print(f"left container {args.container_name} running (--keep)")
        else:
            teardown(args.container_name)


if __name__ == "__main__":
    main()
