#!/usr/bin/env python3
"""
Force immediate PVC cleanup by directly deleting the sandbox.

This script demonstrates the difference between:
1. Deleting a conversation (waits if other conversations share the sandbox)
2. Deleting a sandbox directly (forces immediate cleanup)

When you DELETE a sandbox via the API, it:
- Calls the runtime-api's stop_runtime() function
- Which immediately calls delete_runtime_and_workspace_in_k8s()
- Which deletes ALL Kubernetes resources including the PVC right away

This is faster than waiting for the cleanup cronjob (runs every 5 minutes)
and ensures immediate PVC release for storage quota.

Usage:
    # Force cleanup a specific sandbox
    python force_cleanup.py <sandbox_id>

    # Force cleanup all PAUSED/STOPPED sandboxes
    python force_cleanup.py --cleanup-idle

Requirements:
    - OH_API_KEY environment variable must be set
"""

import os
import sys
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
    }


def list_sandboxes(limit: int = 100) -> list[dict[str, Any]]:
    """List all sandboxes for the authenticated user."""
    url = f"{API_BASE_URL}/api/v1/sandboxes/search"
    params = {"limit": limit}

    response = requests.get(url, headers=get_headers(), params=params)
    response.raise_for_status()

    data = response.json()
    return data.get("items", [])


def get_sandbox(sandbox_id: str) -> dict[str, Any]:
    """Get details for a specific sandbox."""
    # Use batch GET endpoint with single ID (more efficient than search)
    url = f"{API_BASE_URL}/api/v1/sandboxes"
    params = {"id": [sandbox_id]}

    response = requests.get(url, headers=get_headers(), params=params)
    response.raise_for_status()

    sandboxes = response.json()
    
    # Batch endpoint returns array, with null for missing sandboxes
    if sandboxes and sandboxes[0] is not None:
        return sandboxes[0]

    raise ValueError(f"Sandbox {sandbox_id} not found")


def delete_sandbox(sandbox_id: str) -> dict[str, Any]:
    """
    Force immediate deletion of a sandbox and all its resources.

    This directly calls the runtime-api's stop endpoint which:
    1. Immediately deletes the Kubernetes Deployment
    2. Immediately deletes the PVC → Releases storage!
    3. Deletes Service, Ingress/HTTPRoute, ServiceAccount, PDB
    4. Deletes VolumeSnapshot if any

    Unlike conversation deletion which waits if other conversations share
    the sandbox, this FORCES immediate cleanup regardless.

    Args:
        sandbox_id: The sandbox ID to delete

    Returns:
        Response data from the delete operation
    """
    # Note: API requires sandbox_id in both path AND query parameter
    # Path param: /api/v1/sandboxes/{id}
    # Query param: ?sandbox_id=...
    url = f"{API_BASE_URL}/api/v1/sandboxes/{sandbox_id}"
    params = {"sandbox_id": sandbox_id}

    response = requests.delete(url, headers=get_headers(), params=params)
    response.raise_for_status()

    return response.json()


def pause_sandbox(sandbox_id: str) -> dict[str, Any]:
    """
    Pause a sandbox (scales deployment to 0 but keeps PVC).

    This is different from delete - the PVC is preserved.
    
    Note: This function is included for documentation purposes to demonstrate
    the pause API endpoint, even though it's not used by the CLI commands.
    """
    url = f"{API_BASE_URL}/api/v1/sandboxes/{sandbox_id}/pause"

    response = requests.post(url, headers=get_headers())
    response.raise_for_status()

    return response.json()


def print_sandbox_summary(sandbox: dict[str, Any]) -> None:
    """Print a formatted summary of a sandbox."""
    print(f"  ID: {sandbox.get('id')}")
    print(f"  Status: {sandbox.get('status')}")
    print(f"  Created: {sandbox.get('created_at')}")
    print(f"  Spec: {sandbox.get('sandbox_spec_id')}")
    print()


def cmd_force_delete(sandbox_id: str):
    """Force delete a specific sandbox."""
    print(f"Force deleting sandbox {sandbox_id}...\n")

    # Get sandbox details
    try:
        sandbox = get_sandbox(sandbox_id)
        print("Sandbox details:")
        print_sandbox_summary(sandbox)

    except Exception as e:
        print(f"Warning: Could not get sandbox details: {e}")
        print()

    # Confirm deletion
    print("⚠️  WARNING: This will IMMEDIATELY delete the sandbox and release its PVC.")
    print("    This action cannot be undone!")
    print()
    confirm = input("Type 'DELETE' to confirm: ")
    if confirm != "DELETE":
        print("Cancelled.")
        return

    print()

    # Delete the sandbox
    try:
        result = delete_sandbox(sandbox_id)
        print(f"✓ Successfully deleted sandbox {sandbox_id}")
        print(f"Response: {result}")
        print()
        print("Resources deleted:")
        print("  ✓ Kubernetes Deployment")
        print("  ✓ PersistentVolumeClaim (PVC) → Storage released!")
        print("  ✓ Service, Ingress/HTTPRoute")
        print("  ✓ ServiceAccount, PodDisruptionBudget")
        print("  ✓ VolumeSnapshot (if any)")
        print()
        print("The PVC has been released immediately! ✨")

    except requests.exceptions.HTTPError as e:
        if e.response.status_code == 404:
            print(f"Sandbox {sandbox_id} not found (may already be deleted)")
        else:
            print(f"Error deleting sandbox: {e}")
            raise


def cmd_cleanup_idle():
    """Force delete all PAUSED or STOPPED sandboxes."""
    print("Fetching sandboxes...\n")

    sandboxes = list_sandboxes()

    # Filter to PAUSED/STOPPED/MISSING sandboxes
    idle = [
        sb for sb in sandboxes if sb.get("status") in ["PAUSED", "STOPPED", "MISSING"]
    ]

    if not idle:
        print("No idle sandboxes found to clean up.")
        return

    print(f"Found {len(idle)} idle sandbox(es) to clean up:\n")

    for i, sb in enumerate(idle, 1):
        print(f"{i}. {sb.get('id')} - {sb.get('status')}")

    print()
    msg = (
        "⚠️  WARNING: This will IMMEDIATELY delete all these sandboxes "
        "and release their PVCs."
    )
    print(msg)
    confirm = input("Type 'DELETE ALL' to confirm: ")
    if confirm != "DELETE ALL":
        print("Cancelled.")
        return

    print()
    for sb in idle:
        sb_id = sb.get("id")
        try:
            delete_sandbox(sb_id)
            print(f"✓ Deleted sandbox {sb_id} ({sb.get('status')})")
        except Exception as e:
            print(f"✗ Failed to delete sandbox {sb_id}: {e}")

    print(f"\n✓ Cleanup complete. {len(idle)} sandbox(es) deleted.")


def cmd_list():
    """List all sandboxes with their status."""
    print("Fetching sandboxes...\n")

    sandboxes = list_sandboxes()

    if not sandboxes:
        print("No sandboxes found.")
        return

    print(f"Found {len(sandboxes)} sandbox(es):\n")

    # Group by status
    by_status = {}
    for sb in sandboxes:
        status = sb.get("status", "UNKNOWN")
        by_status.setdefault(status, []).append(sb)

    for status, sbs in sorted(by_status.items()):
        print(f"{status}: {len(sbs)}")
        for sb in sbs:
            print(f"  - {sb.get('id')} (created {sb.get('created_at')})")
        print()


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)

    command = sys.argv[1]

    if command == "--cleanup-idle":
        cmd_cleanup_idle()
    elif command == "--list":
        cmd_list()
    elif command.startswith("-"):
        print(f"Unknown option: {command}")
        print(__doc__)
        sys.exit(1)
    else:
        # Treat as sandbox_id
        sandbox_id = command
        cmd_force_delete(sandbox_id)


if __name__ == "__main__":
    main()
