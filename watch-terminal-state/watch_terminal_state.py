#!/usr/bin/env python3
"""Detect the *terminal* state of a Cloud conversation over the WebSocket.

A deep-dive follow-on to ``../react-to-state-websocket``. That example shows the
basics: start a Cloud sandbox, attach a conversation (no LLM key needed), open
the agent-server WebSocket (``/sockets/events/{id}``), and print every
``execution_status`` transition. Read it first.

This example keeps the *same Cloud approach* and layers on the details you need
to detect **when a conversation is truly done** and then exit:

    1. Both event shapes. ``ConversationStateUpdateEvent`` arrives two ways:
         * per-field:    key="execution_status", value="finished"
         * full-state:   key="full_state",       value={..., "execution_status": …}
       A robust consumer reads both. ``react-to-state-websocket`` only reads the
       per-field shape (fine for printing transitions); here we handle both.

    2. FINISHED is advisory; ERROR/STUCK are immediate. The SDK treats a
       per-field ``finished`` as provisional because a Stop hook can still revert
       the stop (see ../finish-callback). The authoritative confirmation is the
       ``full_state`` snapshot emitted after the run settles. So we wait for a
       full-state ``finished`` before declaring done, but accept ``error`` /
       ``stuck`` the instant they arrive.

    3. First-message auth. We authenticate with a ``{"type":"auth", …}`` frame
       rather than the deprecated ``?session_api_key=`` query param, keeping the
       session key out of URLs and reverse-proxy access logs.

Nothing polls the conversation's execution state — every signal comes off the
socket. Only the sandbox lifecycle is polled (waiting for RUNNING), exactly as
in ``react-to-state-websocket``.

    export OH_API_KEY=...            # Cloud API key (required)
    pip install requests websockets
    python watch_terminal_state.py

Env vars: OH_API_KEY, OH_API_BASE, SANDBOX_SPEC_ID, POLL_TIMEOUT.
"""

import argparse
import asyncio
import json
import os
import sys
import time

import requests
import websockets


# execution_status values the SDK's ConversationExecutionStatus.is_terminal()
# treats as terminal. IDLE is deliberately excluded — it is also the *initial*
# state before a run starts, so treating it as terminal would fire a false
# positive.
TERMINAL_STATES = {"finished", "error", "stuck"}

# FINISHED alone is advisory: a Stop hook can revert it, so the SDK confirms it
# with the post-run full_state snapshot. ERROR and STUCK are accepted the moment
# they arrive in any shape.
IMMEDIATE_TERMINAL_STATES = {"error", "stuck"}

FULL_STATE_KEY = "full_state"


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
        "--watch-timeout",
        type=int,
        default=180,
        help="Max seconds to watch the socket for a terminal state (default: 180).",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Leave the sandbox running at the end instead of deleting it.",
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
    """POST /api/v1/app-conversations with sandbox_id; poll start-task for its id.

    The Cloud attach call is asynchronous: it returns a *start task*, not the
    conversation. We poll /api/v1/app-conversations/start-tasks until it yields
    an app_conversation_id. This is provisioning latency, not conversation-state
    polling — once we have the id, state is watched over the socket. No LLM key
    is needed: the Cloud layer injects your account's credentials.
    """
    payload = {
        "sandbox_id": sandbox_id,
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": message}],
        },
        "title": "watch-terminal-state",
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


def _status_from_event(event: dict) -> tuple[str | None, bool]:
    """Extract (execution_status, is_full_state) from a state event, if present.

    Returns (None, False) for events that are not a ConversationStateUpdateEvent
    or that carry no execution_status. The second element says whether the value
    came from an authoritative ``full_state`` snapshot (used to confirm a
    provisional ``finished``).
    """
    if event.get("kind") != "ConversationStateUpdateEvent":
        return None, False
    key = event.get("key")
    value = event.get("value")
    if key == "execution_status" and isinstance(value, str):
        return value, False
    if key == FULL_STATE_KEY and isinstance(value, dict):
        return value.get("execution_status"), True
    return None, False


async def watch_terminal_state(
    agent_url: str, session_api_key: str, conversation_id: str, timeout: int
) -> str | None:
    """Subscribe to the event stream and return the confirmed terminal status.

    Connects to ``wss://{agent}/sockets/events/{id}`` and authenticates with a
    first-message ``auth`` frame (keeps the key out of the URL and proxy logs).
    ``resend_mode=all`` replays events already produced since the conversation
    started, closing the create->connect race without polling.

    A per-field ``finished`` is treated as provisional and remembered; we return
    it only once a ``full_state`` snapshot confirms it (or return immediately if
    the snapshot itself reports finished). ``error`` / ``stuck`` return at once.
    """
    ws_base = agent_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_base}/sockets/events/{conversation_id}?resend_mode=all"

    deadline = time.monotonic() + timeout
    provisional_finished = False

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "auth", "session_api_key": session_api_key}))
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

            status, is_full_state = _status_from_event(event)
            if status is None:
                print(f"  .. {event.get('kind', '?')}")
                continue

            shape = "full_state" if is_full_state else "per-field"
            print(f"  >> execution_status={status} ({shape})")

            if status in IMMEDIATE_TERMINAL_STATES:
                return status
            if status == "finished":
                if is_full_state:
                    return status
                # Provisional: a Stop hook could still revert this. Wait for the
                # authoritative full_state snapshot to confirm.
                provisional_finished = True
                print("     (provisional — awaiting full_state confirmation)")
            elif is_full_state and provisional_finished:
                # The run moved on from a provisional finish (e.g. a hook resumed
                # it); drop the provisional flag and keep watching.
                provisional_finished = False


def delete_sandbox(base_url: str, headers: dict, sandbox_id: str) -> None:
    """DELETE the sandbox (id goes in both the path and a query param)."""
    requests.delete(
        f"{base_url}/api/v1/sandboxes/{sandbox_id}",
        headers=headers,
        params={"sandbox_id": sandbox_id},
    )


def main() -> None:
    args = parse_args()
    if not args.api_key:
        sys.exit("error: set --api-key or the OH_API_KEY environment variable")
    headers = {"X-Session-API-Key": args.api_key}

    # 1. Start sandbox.
    sb = start_sandbox(args.base_url, headers, args.sandbox_spec_id)
    sid = sb["id"]
    print("sandbox:", sid)

    # 2. Poll sandbox lifecycle until RUNNING (bounded by --poll-timeout).
    sb = wait_until_running(args.base_url, headers, sid, args.poll_timeout)

    try:
        agent_url = agent_server_url(sb)
        session_api_key = sb["session_api_key"]
        print("agent:", agent_url)

        # 3. Attach a conversation via the Cloud API. No LLM key needed — the
        #    Cloud layer injects your account's credentials. This is async, so
        #    we briefly poll the start task for the conversation id.
        print("\n=== attaching conversation (start-task poll) ===")
        conv_id = attach_conversation(
            args.base_url, headers, sid, args.message, args.poll_timeout
        )
        print("conversation:", conv_id)

        # 4. Watch the socket for a confirmed terminal state — no
        #    conversation-state polling.
        print("\n=== watching for terminal state (WebSocket) ===")
        status = asyncio.run(
            watch_terminal_state(
                agent_url, session_api_key, conv_id, args.watch_timeout
            )
        )
        if status:
            print(f"\nterminal state reached: {status}")
            print("(confirmed over the WebSocket — no polling)")
        else:
            print("\nexiting without a terminal state (timed out)")
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


if __name__ == "__main__":
    main()
