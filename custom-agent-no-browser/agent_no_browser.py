#!/usr/bin/env python3
"""Create a custom agent configuration without the browser tool.

This example demonstrates how to customize agent behavior by selectively
choosing which tools to include. We create an agent that has terminal and
file editing capabilities but explicitly excludes the browser tool.

This is useful when:
  - You want to restrict the agent to local operations only
  - You're working in an environment without internet access
  - You want to reduce the agent's surface area for security or cost reasons
  - You're focusing on code-only tasks without web research

The key insight: OpenHands agents are configured via the Cloud API's
`agent_settings` parameter when creating conversations. You can specify
which tools to include, though the exact behavior may vary by deployment.

Run this example:
    export OH_API_KEY=...        # your https://app.all-hands.dev API key
    python agent_no_browser.py

The script will:
  1. Create a conversation specifying terminal and file_editor tools
  2. Ask the agent to create a Python script
  3. Wait for the agent to complete the task
  4. Clean up the conversation and sandbox (unless --keep is used)
"""

import argparse
import os
import sys
import time

import requests


DEFAULT_MESSAGE = (
    "Create a Python script called 'hello.py' that prints 'Hello, Custom Agent!' "
    "Then show me the file content to confirm it was created."
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Run a custom agent without browser tool.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument(
        "--api-key",
        default=os.environ.get("OH_API_KEY"),
        help="Cloud API key (env: OH_API_KEY).",
    )
    p.add_argument(
        "--base-url",
        default=os.environ.get("OH_API_BASE", "https://app.all-hands.dev"),
        help="Cloud app server base URL (env: OH_API_BASE).",
    )
    p.add_argument(
        "--message",
        default=os.environ.get("INITIAL_MESSAGE", DEFAULT_MESSAGE),
        help="First message for the conversation (env: INITIAL_MESSAGE).",
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Leave the conversation/sandbox running instead of deleting them.",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=int(os.environ.get("POLL_TIMEOUT", "240")),
        help="Seconds to wait for conversation readiness (env: POLL_TIMEOUT).",
    )
    return p.parse_args()


def start_conversation(base_url: str, headers: dict, args: argparse.Namespace) -> str:
    """Create a conversation with custom agent configuration.

    The key part: we pass `agent_settings` to configure the agent with
    only the tools we want. Here we explicitly include terminal and file_editor,
    but omit the browser tool.

    Note: The Cloud API's tool configuration behavior may vary. In some
    deployments, agent_settings.tools may be advisory rather than strictly
    enforced. Check the actual tools available in your conversation.
    """
    payload = {
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": args.message}],
        },
        "title": "custom-agent-no-browser demo",
        # This is where we customize the agent!
        "agent_settings": {
            "tools": [
                {"name": "terminal"},      # ✅ Terminal access
                {"name": "file_editor"},   # ✅ File editing
                # ❌ No browser tool!
            ],
        },
    }

    resp = requests.post(
        f"{base_url}/api/v1/app-conversations", headers=headers, json=payload
    )
    resp.raise_for_status()
    task = resp.json()
    conv_id = task.get("app_conversation_id")
    task_id = task["id"]

    # Poll until the conversation is created
    deadline = time.monotonic() + args.poll_timeout
    while not conv_id:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Start task {task_id} never produced a conversation")
        time.sleep(3)
        resp = requests.get(
            f"{base_url}/api/v1/app-conversations/start-tasks",
            headers=headers,
            params={"ids": task_id},
        )
        resp.raise_for_status()
        items = resp.json()
        item = items[0] if isinstance(items, list) else items
        status = item.get("status")
        print(f"  start-task status: {status}")
        conv_id = item.get("app_conversation_id")
    return conv_id


def get_conversation(base_url: str, headers: dict, conv_id: str) -> dict:
    """Fetch the conversation details."""
    resp = requests.get(
        f"{base_url}/api/v1/app-conversations",
        headers=headers,
        params={"ids": conv_id},
    )
    resp.raise_for_status()
    results = resp.json()
    if not results or results[0] is None:
        raise ValueError(f"Conversation {conv_id} not found")
    return results[0]


def wait_until_ready(base_url: str, headers: dict, conv_id: str, timeout: int) -> dict:
    """Poll until the sandbox is RUNNING."""
    deadline = time.monotonic() + timeout
    while True:
        conv = get_conversation(base_url, headers, conv_id)
        status = conv.get("sandbox_status")
        print(f"  sandbox status: {status}")
        if status == "RUNNING":
            return conv
        if time.monotonic() > deadline:
            raise TimeoutError(f"Conversation {conv_id} not ready within {timeout}s")
        time.sleep(3)


def wait_for_agent_completion(
    base_url: str, headers: dict, conv_id: str, timeout: int = 300
):
    """Wait for the agent to finish processing (execution_status = finished)."""
    deadline = time.monotonic() + timeout
    print("\n=== waiting for agent to complete task ===")
    while True:
        conv = get_conversation(base_url, headers, conv_id)
        execution_status = conv.get("execution_status", "unknown")
        print(f"  execution status: {execution_status}")

        if execution_status == "finished":
            print("  ✓ agent completed the task")
            return

        if execution_status == "error":
            print("  ✗ agent encountered an error")
            return

        if time.monotonic() > deadline:
            print(f"  ⚠ agent still working after {timeout}s")
            return

        time.sleep(5)


def cleanup(base_url: str, headers: dict, conv_id: str, sandbox_id: str | None) -> None:
    """Delete the conversation and sandbox."""
    requests.delete(f"{base_url}/api/v1/app-conversations/{conv_id}", headers=headers)
    print(f"  deleted conversation {conv_id}")
    if sandbox_id:
        requests.delete(
            f"{base_url}/api/v1/sandboxes/{sandbox_id}",
            headers=headers,
            params={"sandbox_id": sandbox_id},
        )
        print(f"  deleted sandbox {sandbox_id}")


def main() -> None:
    args = parse_args()
    if not args.api_key:
        sys.exit("error: set --api-key or the OH_API_KEY environment variable")

    headers = {"X-Session-API-Key": args.api_key}

    print("=== creating conversation with custom agent (no browser) ===")
    print(f"Task: {args.message}\n")

    # Start the conversation with our custom agent configuration
    conv_id = start_conversation(args.base_url, headers, args)
    print(f"conversation: {conv_id}")

    # Wait for sandbox to be ready
    conv = wait_until_ready(args.base_url, headers, conv_id, args.poll_timeout)
    sandbox_id = conv.get("sandbox_id")

    # Wait for the agent to complete the task
    wait_for_agent_completion(args.base_url, headers, conv_id)

    # Show the result
    print("\n=== result ===")
    conv_url = f"{args.base_url}/conversations/{conv_id}"
    print(f"View the conversation: {conv_url}")
    print("\nThe agent completed the task.")
    print("To verify which tools were actually available, check the conversation UI.")

    # Clean up or keep
    if args.keep:
        print(f"\nLeft running (--keep). Open: {conv_url}")
    else:
        print("\n=== cleanup ===")
        cleanup(args.base_url, headers, conv_id, sandbox_id)


if __name__ == "__main__":
    main()
