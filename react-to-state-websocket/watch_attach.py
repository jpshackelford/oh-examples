#!/usr/bin/env python3
"""Attach a conversation via the Cloud API, then watch its state over a socket.

This is the "no LLM key" approach. The conversation is created through the
**Cloud app server** (``POST /api/v1/app-conversations`` with a ``sandbox_id``),
so the Cloud layer injects your account's configured LLM credentials — you never
pass a model or API key. The trade-off: that call is asynchronous and returns a
*start task*, so there is a brief poll of ``start-tasks`` to learn the
conversation id before the socket can be opened.

Once the id is known, it connects to the sandbox agent-server's WebSocket
(``/sockets/events/{id}``) and reacts to ``execution_status`` transitions as they
arrive — no polling of the conversation's execution state.

Compare with ``watch_direct.py``, which avoids the start-task poll by creating
the conversation straight on the agent-server, at the cost of supplying LLM
credentials. See the README for the full trade-off.

    export OH_API_KEY=...            # Cloud API key (required)
    pip install requests websockets
    python watch_attach.py

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


# Conversation execution states the agent-server can report. The stream is
# considered done once one of these terminal states arrives.
TERMINAL_STATES = {"finished", "error", "stuck"}


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
        default="Say hello, then stop.",
        help="Initial user message for the conversation.",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=int(os.environ.get("POLL_TIMEOUT", "180")),
        help="Seconds to wait for the sandbox / start task (default: 180).",
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
    polling — once we have the id, state is watched over the socket.
    """
    payload = {
        "sandbox_id": sandbox_id,
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": message}],
        },
        "title": "react-to-state-websocket (attach)",
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


async def watch_states(
    agent_url: str, session_api_key: str, conversation_id: str
) -> None:
    """Subscribe to the event stream and react to state transitions.

    Connects to ``wss://{agent}/sockets/events/{id}`` and authenticates with a
    first-message ``auth`` frame (keeps the key out of the URL and proxy logs).
    ``resend_mode=all`` replays events already produced since the conversation
    started, closing the create->connect race without polling. Returns once a
    terminal execution status arrives.
    """
    ws_base = agent_url.replace("https://", "wss://").replace("http://", "ws://")
    ws_url = f"{ws_base}/sockets/events/{conversation_id}?resend_mode=all"

    async with websockets.connect(ws_url) as ws:
        await ws.send(json.dumps({"type": "auth", "session_api_key": session_api_key}))

        while True:
            event = json.loads(await ws.recv())
            kind = event.get("kind")
            if kind == "ConversationStateUpdateEvent":
                if event.get("key") == "execution_status":
                    status = event.get("value")
                    print(f"  >> execution_status: {status}")
                    if status in TERMINAL_STATES:
                        return
            elif kind:
                # Surface other events (messages, actions, errors) for context.
                print(f"  .. {kind}")


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

        # 4. Subscribe over WebSocket and react to state changes — no
        #    conversation-state polling.
        print("\n=== watching conversation state (WebSocket) ===")
        asyncio.run(watch_states(agent_url, session_api_key, conv_id))
        print("=== done ===")
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
