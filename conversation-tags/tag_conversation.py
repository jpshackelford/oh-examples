#!/usr/bin/env python3
"""Attach arbitrary key-value metadata to a conversation using *tags*.

OpenHands conversations carry a free-form ``tags`` map (lowercase-alphanumeric
keys, string values up to 256 chars). It is the supported way to stash your own
metadata on a conversation -- e.g. an external ``environment_url`` or
``environment_conversation_id`` -- and read it back later from your own tooling.

This example shows the full round-trip:

  1. Start a conversation via the Cloud app server
     (``POST /api/v1/app-conversations``).
  2. Resolve its agent-server ``conversation_url`` + per-conversation
     ``session_api_key`` (``GET /api/v1/app-conversations?ids=``).
  3. Set tags on the **agent server**
     (``PATCH {conversation_url}`` with ``{"tags": {...}}``).
  4. Read the tags back from the **Cloud** app server -- they surface on
     ``AppConversation.tags`` -- proving the two servers agree.

Why the agent server for writing? Tags are a property of the agent-side
conversation. The Cloud create/update calls do not (yet) expose ``tags``, but
the value you set on the agent server is reflected in the Cloud
``AppConversation.tags`` field. ``conversation_url`` returned by the Cloud is
already the full agent resource URL ``https://<agent-host>/api/conversations/<id>``.

  Two servers, two keys:
    - Cloud app server : header ``X-Session-API-Key: <OH_API_KEY>``
    - Agent server     : header ``X-Session-API-Key: <session_api_key>``
      (the per-conversation key returned by the Cloud).

Tag rules (enforced by the agent server):
    - keys must be **lowercase alphanumeric** (no ``_`` or ``-``)
    - values are arbitrary strings, **<= 256 characters**
    - ``PATCH`` **replaces all** tags -- so we read-modify-write to merge.

Everything is configurable via flags or environment variables:

    export OH_API_KEY=...                     # Cloud API key (required)
    python tag_conversation.py                # sets two demo tags

    python tag_conversation.py \
        --tag environmenturl=https://env.example.com/abc \
        --tag environmentconversationid=ext-42 \
        --keep
"""

import argparse
import os
import re
import sys
import time

import requests


DEFAULT_MESSAGE = "Say hello in one short sentence."
DEFAULT_TAGS = [
    "environmenturl=https://env.example.com/session/abc123",
    "environmentconversationid=ext-0001",
]
KEY_RE = re.compile(r"^[a-z0-9]+$")
MAX_VALUE_LEN = 256


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Attach key-value metadata to a conversation via tags.",
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
        "--tag",
        action="append",
        metavar="KEY=VALUE",
        help="Tag to set (repeatable). Defaults to two demo tags if omitted.",
    )
    p.add_argument(
        "--message",
        default=os.environ.get("INITIAL_MESSAGE", DEFAULT_MESSAGE),
        help="First message for the conversation (env: INITIAL_MESSAGE).",
    )
    p.add_argument(
        "--sandbox-id",
        default=os.environ.get("SANDBOX_ID"),
        help="Reuse an existing RUNNING sandbox instead of creating one "
        "(env: SANDBOX_ID).",
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


def parse_tags(pairs: list[str]) -> dict[str, str]:
    """Turn ``KEY=VALUE`` strings into a validated tag dict."""
    tags: dict[str, str] = {}
    for raw in pairs:
        if "=" not in raw:
            sys.exit(f"error: --tag must be KEY=VALUE, got {raw!r}")
        key, value = raw.split("=", 1)
        if not KEY_RE.match(key):
            sys.exit(
                f"error: tag key {key!r} is invalid -- keys must be lowercase "
                "alphanumeric (no '_' or '-'). e.g. use 'environmenturl' not "
                "'environment_url'."
            )
        if len(value) > MAX_VALUE_LEN:
            sys.exit(
                f"error: tag {key!r} value is {len(value)} chars; the limit is "
                f"{MAX_VALUE_LEN}. Pack structured data into JSON within that limit."
            )
        tags[key] = value
    return tags


# --- Cloud app server ---------------------------------------------------------


def start_conversation(base_url: str, headers: dict, args: argparse.Namespace) -> str:
    """POST /api/v1/app-conversations -> resolve the app_conversation_id.

    The call is asynchronous: it returns a *start task*. Poll
    /api/v1/app-conversations/start-tasks until it yields an app_conversation_id.
    """
    payload: dict = {
        "initial_message": {
            "role": "user",
            "content": [{"type": "text", "text": args.message}],
        },
        "title": "conversation-tags demo",
    }
    if args.sandbox_id:
        payload["sandbox_id"] = args.sandbox_id

    resp = requests.post(
        f"{base_url}/api/v1/app-conversations", headers=headers, json=payload
    )
    resp.raise_for_status()
    task = resp.json()
    conv_id = task.get("app_conversation_id")
    task_id = task["id"]

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
        print("  start-task status:", item.get("status"))
        conv_id = item.get("app_conversation_id")
    return conv_id


def get_app_conversation(base_url: str, headers: dict, conv_id: str) -> dict:
    """GET /api/v1/app-conversations?ids=<id> -> the AppConversation dict."""
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
    """Poll until the sandbox is RUNNING and the agent URL + key are available."""
    deadline = time.monotonic() + timeout
    while True:
        conv = get_app_conversation(base_url, headers, conv_id)
        print("  sandbox status:", conv.get("sandbox_status"))
        if (
            conv.get("sandbox_status") == "RUNNING"
            and conv.get("conversation_url")
            and conv.get("session_api_key")
        ):
            return conv
        if time.monotonic() > deadline:
            raise TimeoutError(f"Conversation {conv_id} not ready within {timeout}s")
        time.sleep(3)


# --- Agent server (owns the tags) ---------------------------------------------


def read_tags(conversation_url: str, session: dict) -> dict[str, str]:
    """GET the agent-side conversation and return its current tags."""
    resp = requests.get(conversation_url, headers=session)
    resp.raise_for_status()
    return resp.json().get("tags") or {}


def set_tags(conversation_url: str, session: dict, tags: dict[str, str]) -> None:
    """PATCH the agent-side conversation with the full tag map.

    PATCH replaces *all* tags, so callers should pass an already-merged map.
    """
    resp = requests.patch(conversation_url, headers=session, json={"tags": tags})
    resp.raise_for_status()


# --- Cleanup ------------------------------------------------------------------


def cleanup(base_url: str, headers: dict, conv_id: str, sandbox_id: str | None) -> None:
    requests.delete(f"{base_url}/api/v1/app-conversations/{conv_id}", headers=headers)
    print("  deleted conversation", conv_id)
    if sandbox_id:
        requests.delete(
            f"{base_url}/api/v1/sandboxes/{sandbox_id}",
            headers=headers,
            params={"sandbox_id": sandbox_id},
        )
        print("  deleted sandbox", sandbox_id)


def main() -> None:
    args = parse_args()
    if not args.api_key:
        sys.exit("error: set --api-key or the OH_API_KEY environment variable")
    new_tags = parse_tags(args.tag if args.tag else DEFAULT_TAGS)
    headers = {"X-Session-API-Key": args.api_key}

    # 1-2. Start a conversation and wait until its sandbox is RUNNING.
    print("=== start conversation ===")
    conv_id = start_conversation(args.base_url, headers, args)
    print("conversation:", conv_id)
    conv = wait_until_ready(args.base_url, headers, conv_id, args.poll_timeout)

    conversation_url = conv["conversation_url"]
    sandbox_id = conv.get("sandbox_id")
    session = {"X-Session-API-Key": conv["session_api_key"]}
    print("agent conversation_url:", conversation_url)

    # 3. Merge our metadata into any existing tags, then write (PATCH replaces all).
    print("\n=== set tags (agent server) ===")
    existing = read_tags(conversation_url, session)
    merged = {**existing, **new_tags}
    print("  existing tags:", existing)
    print("  setting tags: ", merged)
    set_tags(conversation_url, session, merged)

    # 4a. Confirm on the agent server -- authoritative and immediate.
    agent_tags = read_tags(conversation_url, session)
    print("  agent tags (authoritative):", agent_tags)
    ok = all(agent_tags.get(k) == v for k, v in new_tags.items())

    # 4b. Read back from the Cloud app server. The Cloud's AppConversation.tags
    #     view is *eventually consistent* with the agent server (typically a few
    #     seconds), so poll briefly rather than reading once.
    print("\n=== read tags back (cloud server, eventually consistent) ===")
    deadline = time.monotonic() + 30
    cloud_tags: dict = {}
    while True:
        conv = get_app_conversation(args.base_url, headers, conv_id)
        cloud_tags = conv.get("tags") or {}
        if all(cloud_tags.get(k) == v for k, v in new_tags.items()):
            break
        if time.monotonic() > deadline:
            print("  (cloud view not yet consistent after 30s)")
            break
        time.sleep(3)
    print("  AppConversation.tags:", cloud_tags)

    print("\nround-trip OK:", ok)

    # 5. Clean up unless asked to keep it.
    if args.keep:
        url = f"{args.base_url}/conversations/{conv_id}"
        print(f"\nLeft running (--keep). Open: {url}")
    else:
        print("\n=== cleanup ===")
        cleanup(args.base_url, headers, conv_id, sandbox_id)

    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
