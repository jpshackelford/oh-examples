#!/usr/bin/env python3
"""Detect when a conversation finishes over the agent-server WEBSOCKET.

Push, not poll. This script drives a LOCALLY-RUN agent-server (in Docker)
end-to-end and watches conversation state in real time over the V1 WebSocket:

    1. Start the agent-server container from the software-agent-sdk image and
       wait for GET /health to return ok.
    2. Connect to the WebSocket at ``/sockets/events/{conversation_id}`` and
       authenticate with the session key (query parameter).
    3. Create a conversation (POST /api/conversations) with a small
       ``initial_message`` and run it.
    4. Read events off the socket as they happen. Announce the terminal state
       (finished / error / stuck) the moment it arrives, then exit.
       This script NEVER polls conversation state over REST — the only state
       signal is what arrives on the WebSocket.
    5. Tear the container down.

Why this and not the webhook example? The agent-server ``WebhookSpec`` (see
``../react-to-state-webhooks``) is *push from the server*, which needs the
server to be configured with your receiver's URL — impossible on OpenHands
Cloud, where you cannot inject webhook config into a running sandbox. The
WebSocket is *pull-connected by the client*, so it also works against a Cloud
sandbox's agent-server URL (use ``wss://…`` and the sandbox session key). This
demo runs locally so it is fully reproducible without a Cloud account.

Prerequisites: Docker running. Install deps::

    pip install requests websockets

Configure the LLM (same shape as the rest of the repo)::

    export LLM_API_KEY=...                 # required
    export LLM_MODEL=litellm_proxy/...     # required
    export LLM_BASE_URL=https://...        # optional (provider default if unset)
    python watch_ws.py

Env vars: LLM_API_KEY, LLM_MODEL, LLM_BASE_URL, SESSION_API_KEY,
OH_AGENT_SERVER_IMAGE, OH_SERVER_PORT.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from urllib.parse import quote

import requests
import websockets


# execution_status values the SDK treats as terminal (ConversationExecutionStatus
# .is_terminal()). IDLE is deliberately excluded: it is also the *initial* state
# before a run starts, so treating it as terminal would fire a false positive.
TERMINAL_STATUSES = {"finished", "error", "stuck"}


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
        default="oh-ws-demo",
        help="Name for the agent-server container (default: oh-ws-demo).",
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
        "--watch-timeout",
        type=int,
        default=120,
        help="Max seconds to watch the socket for a terminal state (default: 120).",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Leave the container running at the end instead of removing it.",
    )
    return p.parse_args()


def start_container(args: argparse.Namespace) -> None:
    """docker run the agent-server with a session key set via OH_ env var."""
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
        # (see config.py _default_session_api_keys / _default_secret_key). This
        # is the local stand-in for the per-sandbox session key the Cloud
        # sandbox-create call hands back.
        "-e",
        f"SESSION_API_KEY={args.session_key}",
        args.image,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    print(f"container: {result.stdout.strip()[:12]}")


def wait_for_health(base: str, headers: dict, timeout: int) -> None:
    """Poll GET /health until ok (server readiness, NOT conversation state)."""
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
    """POST /api/conversations with a runnable initial_message. Returns id.

    A conversation created with ``run: True`` starts its agent loop on its own,
    so we do not need a separate /run call — the WebSocket will show it move to
    RUNNING and then to a terminal state.
    """
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


def _status_from_state_event(event: dict) -> str | None:
    """Extract execution_status from a ConversationStateUpdateEvent, if present.

    The server sends state two ways over the socket:
      * per-field:  key="execution_status", value="finished"
      * full-state: key="full_state",       value={..., "execution_status": ...}
    """
    if event.get("kind") != "ConversationStateUpdateEvent":
        return None
    key = event.get("key")
    value = event.get("value")
    if key == "execution_status" and isinstance(value, str):
        return value
    if key == "full_state" and isinstance(value, dict):
        return value.get("execution_status")
    return None


async def watch_socket(
    ws_base: str, conversation_id: str, session_key: str, timeout: int
) -> str | None:
    """Connect, print events as they arrive, return the first terminal status.

    Auth is via the ``session_api_key`` query parameter (the agent-server also
    supports a first-message ``{"type":"auth", ...}`` frame; the query param is
    simpler here and is exactly what the SDK's own RemoteConversation uses).
    """
    url = f"{ws_base}/sockets/events/{conversation_id}"
    url += f"?session_api_key={quote(session_key, safe='')}"
    # resend_mode=all replays events already emitted before we connected, so a
    # fast run that finishes during container startup is not missed.
    url += "&resend_mode=all"

    print(f"ws: connecting to {ws_base}/sockets/events/{conversation_id}")
    deadline = time.monotonic() + timeout
    async with websockets.connect(url) as ws:
        print("ws: connected — waiting for terminal state (no REST polling)\n")
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                print(f"\nws: no terminal state within {timeout}s")
                return None
            try:
                raw = await asyncio.wait_for(ws.recv(), timeout=remaining)
            except asyncio.TimeoutError:
                print(f"\nws: no terminal state within {timeout}s")
                return None

            try:
                event = json.loads(raw)
            except (ValueError, TypeError):
                continue
            if not isinstance(event, dict):
                continue

            kind = event.get("kind", "?")
            status = _status_from_state_event(event)
            if status:
                print(f"  [event] {kind}  execution_status={status}")
            else:
                print(f"  [event] {kind}")

            if status in TERMINAL_STATUSES:
                return status


def teardown(name: str) -> None:
    subprocess.run(["docker", "rm", "-f", name], check=False, capture_output=True)
    print(f"removed container {name}")


def main() -> None:
    args = parse_args()
    if not args.llm_api_key or not args.llm_model:
        sys.exit("error: set --llm-api-key/--llm-model or $LLM_API_KEY/$LLM_MODEL")

    base = f"http://localhost:{args.server_port}"
    ws_base = f"ws://localhost:{args.server_port}"
    headers = {"X-Session-API-Key": args.session_key}

    try:
        start_container(args)
        wait_for_health(base, headers, args.health_timeout)
        cid = create_conversation(
            base,
            headers,
            args.llm_model,
            args.llm_base_url,
            args.llm_api_key,
            args.message,
        )
        status = asyncio.run(
            watch_socket(ws_base, cid, args.session_key, args.watch_timeout)
        )
        if status:
            print(f"\nterminal state reached: {status}")
            print("(this signal arrived over the WebSocket — no polling)")
        else:
            print("\nexiting without a terminal state (timed out)")
    finally:
        if args.keep:
            print(f"left container {args.container_name} running (--keep)")
        else:
            teardown(args.container_name)


if __name__ == "__main__":
    main()
