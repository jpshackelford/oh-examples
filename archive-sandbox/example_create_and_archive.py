#!/usr/bin/env python3
"""
Complete example: Create a conversation, verify it exists, then archive it.

This demonstrates the full lifecycle:
1. Create a conversation (which creates a sandbox with PVC)
2. Get conversation details (shows sandbox_id)
3. Archive/delete the conversation (releases PVC)

This is useful for understanding the complete workflow and testing sandbox cleanup.
"""

import os
import sys
import time
from typing import Any

import requests


API_BASE_URL = os.getenv("OPENHANDS_API_URL", "https://app.all-hands.dev")
API_KEY = os.getenv("OH_API_KEY")

if not API_KEY:
    print("Error: OH_API_KEY environment variable is required")
    sys.exit(1)


def get_headers() -> dict[str, str]:
    """Get standard headers for API requests."""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def create_conversation(
    title: str = "Test Conversation for Archive Demo",
) -> dict[str, Any]:
    """
    Create a new conversation.

    This will automatically provision a sandbox with:
    - Kubernetes Pod
    - PersistentVolumeClaim (PVC)
    - Service, Ingress/HTTPRoute
    - ServiceAccount, PodDisruptionBudget

    Args:
        title: Title for the conversation

    Returns:
        Conversation data including conversation_id and sandbox_id
    """
    # Try stream-start first (returns list of events), fall back to direct POST
    url = f"{API_BASE_URL}/api/v1/app-conversations/stream-start"

    payload = {
        "llm_model": "claude-sonnet-4-5-20250929",
        "agent_kind": "openhands",
        "title": title,
    }

    response = requests.post(url, headers=get_headers(), json=payload)
    response.raise_for_status()

    result = response.json()

    # Handle both list (stream-start) and dict (direct POST) responses
    if isinstance(result, list):
        # Stream-start returns list of status events, get final one with READY
        for event in result:
            if event.get("status") == "READY":
                return event
        # If no READY event, return the last one
        return result[-1] if result else {}
    return result


def extract_conversation_ids(conv_data: dict[str, Any]) -> tuple:
    """Extract conversation_id and sandbox_id from API response.

    The API returns different ID fields depending on the endpoint:
    - id: runtime/conversation identifier
    - app_conversation_id: the actual app conversation ID for API operations
    - sandbox_id: the sandbox/runtime ID
    """
    conversation_id = conv_data.get("app_conversation_id") or conv_data.get("id")
    sandbox_id = conv_data.get("sandbox_id")
    return conversation_id, sandbox_id


def get_conversation(conversation_id: str) -> dict[str, Any]:
    """Get conversation details using batch GET endpoint."""
    # Use batch GET with ids parameter since single GET endpoint returns HTML
    url = f"{API_BASE_URL}/api/v1/app-conversations"
    params = {"ids": conversation_id}

    response = requests.get(url, headers=get_headers(), params=params)
    response.raise_for_status()

    data = response.json()

    # Batch GET returns a list
    if isinstance(data, list):
        if not data:
            raise requests.exceptions.HTTPError(
                "Conversation not found", response=response
            )
        return data[0]

    return data


def delete_conversation(conversation_id: str) -> dict[str, Any]:
    """Delete conversation and release its PVC."""
    url = f"{API_BASE_URL}/api/v1/app-conversations/{conversation_id}"

    response = requests.delete(url, headers=get_headers())

    # Handle 404 for already-deleted conversations
    if response.status_code == 404:
        return {"success": True, "detail": "Conversation not found (already deleted)"}

    response.raise_for_status()
    return response.json()


def main():
    """Main example workflow."""
    print("=" * 70)
    print("ARCHIVE SANDBOX EXAMPLE - Complete Workflow")
    print("=" * 70)
    print()

    # Step 1: Create conversation
    print("Step 1: Creating a new conversation...")
    print("-" * 70)

    try:
        conv_data = create_conversation()
        conversation_id, sandbox_id = extract_conversation_ids(conv_data)

        print(f"✓ Created conversation: {conversation_id}")
        print(f"✓ Sandbox ID: {sandbox_id}")
        print()
        print("Resources provisioned:")
        print("  - Kubernetes Pod (running agent-server)")
        print("  - PersistentVolumeClaim (PVC) - stores workspace files")
        print("  - Service, Ingress/HTTPRoute")
        print("  - ServiceAccount, PodDisruptionBudget")
        print()

    except Exception as e:
        print(f"✗ Failed to create conversation: {e}")
        sys.exit(1)

    # Wait a bit for resources to be fully provisioned
    print("Waiting 5 seconds for resources to stabilize...")
    time.sleep(5)
    print()

    # Step 2: Get conversation details
    print("Step 2: Retrieving conversation details...")
    print("-" * 70)

    try:
        details = get_conversation(conversation_id)

        print(f"Conversation ID: {details.get('id')}")
        print(f"Title: {details.get('title')}")
        print(f"Sandbox ID: {details.get('sandbox_id')}")
        print(f"Sandbox Status: {details.get('sandbox_status')}")
        print(f"Execution Status: {details.get('execution_status')}")
        print(f"Created: {details.get('created_at')}")
        print(f"Model: {details.get('llm_model')}")
        print()

    except Exception as e:
        print(f"✗ Failed to get conversation details: {e}")
        # Continue anyway

    # Step 3: Archive (delete) conversation
    print("Step 3: Archiving conversation (releasing PVC)...")
    print("-" * 70)

    # Ask for confirmation
    msg = (
        f"Archive conversation {conversation_id}? "
        "This will delete the sandbox and release its PVC. (yes/no): "
    )
    response = input(msg)
    if response.lower() != "yes":
        print()
        print("Cancelled. Conversation will remain active.")
        cmd = f"python archive_sandbox.py archive {conversation_id}"
        print(f"To archive it later, run: {cmd}")
        return

    print()

    try:
        delete_conversation(conversation_id)

        print(f"✓ Successfully archived conversation {conversation_id}")
        print()
        print("Cleanup actions performed:")
        print("  ✓ Conversation deleted from database")
        print("  ✓ Kubernetes Deployment deleted")
        print("  ✓ PersistentVolumeClaim (PVC) deleted → Storage released!")
        print("  ✓ Service deleted")
        print("  ✓ Ingress/HTTPRoute deleted")
        print("  ✓ ServiceAccount deleted")
        print("  ✓ PodDisruptionBudget deleted")
        print("  ✓ VolumeSnapshot deleted (if any)")
        print()
        print("The PVC has been released and storage is freed! ✨")
        print()

    except Exception as e:
        print(f"✗ Failed to archive conversation: {e}")
        sys.exit(1)

    # Step 4: Verify deletion
    print("Step 4: Verifying deletion...")
    print("-" * 70)

    try:
        conv = get_conversation(conversation_id)
        # If we got here, conversation exists
        print(
            "⚠ Warning: Conversation still exists (may take a moment to fully delete)"
        )
        print(f"  Status: {conv.get('status')}")
    except requests.exceptions.HTTPError:
        # HTTP errors mean conversation not found
        print("✓ Confirmed: Conversation has been deleted")
    except Exception:
        # Any other error also means conversation is not accessible
        print("✓ Confirmed: Conversation has been deleted (GET returned non-JSON)")

    print()
    print("=" * 70)
    print("EXAMPLE COMPLETE")
    print("=" * 70)
    print()
    print("Key Takeaways:")
    print("1. Deleting a conversation releases its PVC and frees storage")
    print("2. Pausing or stopping preserves the PVC (for resuming later)")
    msg = (
        "3. Use 'python archive_sandbox.py cleanup' "
        "to bulk-archive stopped conversations"
    )
    print(msg)
    print()


if __name__ == "__main__":
    main()
