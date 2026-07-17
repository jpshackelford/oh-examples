#!/usr/bin/env python3
"""Create a conversation on the agent-server, then watch its state over a socket.

This is the "no start-task poll" approach. The conversation is created directly
on the sandbox **agent-server** (``POST /api/conversations``), which returns the
conversation id synchronously — so there is no ``start-tasks`` polling. The
trade-off: a conversation created this way does **not** inherit any Cloud LLM
credentials, so you must supply your own model and API key.

It then connects to the agent-server WebSocket (``/sockets/events/{id}``) and
reacts to ``execution_status`` transitions as they arrive — no polling of the
conversation's execution state.

Compare with ``watch_attach.py``, which needs no LLM key (the Cloud layer
injects credentials) but must poll a start task to learn the conversation id.
See the README for the full trade-off.

    export OH_API_KEY=...            # Cloud API key (required)
    export LLM_API_KEY=...           # model key (required for this approach)
    pip install requests websockets
    python watch_direct.py --llm-model gpt-4o-mini

Env vars: OH_API_KEY, OH_API_BASE, SANDBOX_SPEC_ID, LLM_MODEL, LLM_API_KEY,
LLM_BASE_URL, POLL_TIMEOUT.
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
        "--llm-model",
        default=os.environ.get("LLM_MODEL", "gpt-4o-mini"),
        help="Model the sandbox agent should use (default: $LLM_MODEL or gpt-4o-mini).",
    )
    p.add_argument(
        "--llm-api-key",
        default=os.environ.get("LLM_API_KEY"),
        help=(
            "API key for the LLM (default: $LLM_API_KEY). Required: a conversation "
            "created directly on the agent-server does not inherit any Cloud LLM "
            "credentials, so you must supply your own."
        ),
    )
    p.add_argument(
        "--llm-base-url",
        default=os.environ.get("LLM_BASE_URL"),
        help="Optional custom LLM base URL / proxy endpoint (default: $LLM_BASE_URL).",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=int(os.environ.get("POLL_TIMEOUT", "180")),
        help="Seconds to wait for the sandbox to reach RUNNING (default: 180).",
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


def build_llm(model: str, api_key: str | None, base_url: str | None) -> dict:
    """Assemble the ``llm`` block for a conversation-start request."""
    llm: dict = {"model": model, "service_id": "agent"}
    if api_key:
        llm["api_key"] = api_key
    if base_url:
        llm["base_url"] = base_url
    return llm


def start_conversation(agent_url: str, session: dict, message: str, llm: dict) -> str:
    """POST /api/conversations on the agent server; return the conversation id.

    Returns the id synchronously (no start task). Providing ``initial_message``
    makes the agent-server start running the conversation immediately, so there
    is no separate "run" call to make. We subscribe with ``resend_mode=all``
    (see ``watch_states``) so transitions between create and connect are
    replayed rather than missed.
    """
    body = {
        "workspace": {"kind": "LocalWorkspace", "working_dir": "/workspace/project"},
        "agent": {"kind": "Agent", "llm": llm},
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": message}],
        },
    }
    resp = requests.post(
        f"{agent_url}/api/conversations", headers=session, json=body, timeout=60
    )
    resp.raise_for_status()
    return resp.json()["id"]


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
    if not args.llm_api_key:
        sys.exit("error: set --llm-api-key or the LLM_API_KEY environment variable")
    headers = {"X-Session-API-Key": args.api_key}
    llm = build_llm(args.llm_model, args.llm_api_key, args.llm_base_url)

    # 1. Start sandbox.
    sb = start_sandbox(args.base_url, headers, args.sandbox_spec_id)
    sid = sb["id"]
    print("sandbox:", sid)

    # 2. Poll sandbox lifecycle until RUNNING (bounded by --poll-timeout).
    sb = wait_until_running(args.base_url, headers, sid, args.poll_timeout)

    try:
        agent_url = agent_server_url(sb)
        session_api_key = sb["session_api_key"]
        session = {"X-Session-API-Key": session_api_key}
        print("agent:", agent_url)

        # 3. Create the conversation directly on the agent-server. Returns the
        #    id synchronously (no start-task poll). With an initial_message it
        #    starts running immediately.
        conv_id = start_conversation(agent_url, session, args.message, llm)
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
