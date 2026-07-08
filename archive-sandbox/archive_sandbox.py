#!/usr/bin/env python3
"""
Example script demonstrating how to archive/delete a conversation to release its PVC.

This script shows how to:
1. List your conversations
2. Delete a specific conversation, which triggers sandbox cleanup
3. Verify that the sandbox resources (including PVC) are released

When you delete a conversation, OpenHands Cloud will:
- Stop the conversation if it's still running
- Clean up the associated sandbox (runtime) resources if no other conversations use it
- Delete the Kubernetes resources including the PVC, freeing up storage

Usage:
    # List conversations
    python archive_sandbox.py list

    # Archive a specific conversation
    python archive_sandbox.py archive <conversation_id>

    # Archive all stopped conversations
    python archive_sandbox.py cleanup

Requirements:
    - OH_API_KEY environment variable must be set
    - requests library: pip install requests
"""

import os
import sys
import requests
from typing import Dict, List, Any


# Configuration
API_BASE_URL = os.getenv("OPENHANDS_API_URL", "https://app.all-hands.dev")
API_KEY = os.getenv("OH_API_KEY")

if not API_KEY:
    print("Error: OH_API_KEY environment variable is required")
    sys.exit(1)


def get_headers() -> Dict[str, str]:
    """Get standard headers for API requests."""
    return {
        "Authorization": f"Bearer {API_KEY}",
        "Accept": "application/json",
    }


def list_conversations(limit: int = 100) -> List[Dict[str, Any]]:
    """
    List all conversations for the authenticated user.
    
    Returns:
        List of conversation objects with details including sandbox_id, status, etc.
    """
    url = f"{API_BASE_URL}/api/v1/app-conversations/search"
    params = {"limit": limit}
    
    response = requests.get(url, headers=get_headers(), params=params)
    response.raise_for_status()
    
    data = response.json()
    return data.get("items", [])


def get_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Get details for a specific conversation.
    
    Args:
        conversation_id: The conversation ID to retrieve
        
    Returns:
        Conversation object with details
    """
    # Use batch GET with ids parameter since single GET endpoint returns HTML
    url = f"{API_BASE_URL}/api/v1/app-conversations"
    params = {"ids": conversation_id}
    
    response = requests.get(url, headers=get_headers(), params=params)
    response.raise_for_status()
    
    data = response.json()
    
    # Batch GET returns a list
    if isinstance(data, list):
        if not data:
            raise ValueError(f"Conversation {conversation_id} not found")
        return data[0]
    
    return data


def delete_conversation(conversation_id: str) -> Dict[str, Any]:
    """
    Delete a conversation and clean up its sandbox resources.
    
    This will:
    1. Stop the conversation if it's still running
    2. Clean up the sandbox (runtime) if no other conversations use it
    3. Delete Kubernetes resources including:
       - Deployment
       - Service
       - ServiceAccount
       - PersistentVolumeClaim (PVC) - this releases the storage!
       - PodDisruptionBudget
       - HTTPRoute/Ingress
       - VolumeSnapshot (if any)
    
    Args:
        conversation_id: The conversation ID to delete
        
    Returns:
        Response data from the delete operation
    """
    url = f"{API_BASE_URL}/api/v1/app-conversations/{conversation_id}"
    
    response = requests.delete(url, headers=get_headers())
    
    # Handle 404 for already-deleted conversations
    if response.status_code == 404:
        return {"success": True, "detail": "Conversation not found (already deleted)"}
    
    response.raise_for_status()
    return response.json()


def print_conversation_summary(conv: Dict[str, Any]) -> None:
    """Print a formatted summary of a conversation."""
    print(f"  ID: {conv.get('id')}")
    print(f"  Title: {conv.get('title')}")
    print(f"  Sandbox ID: {conv.get('sandbox_id')}")
    print(f"  Sandbox Status: {conv.get('sandbox_status')}")
    print(f"  Execution Status: {conv.get('execution_status')}")
    print(f"  Created: {conv.get('created_at')}")
    print(f"  Updated: {conv.get('updated_at')}")
    
    # Show cost metrics if available
    metrics = conv.get('metrics', {})
    if metrics:
        cost = metrics.get('accumulated_cost', 0)
        print(f"  Cost: ${cost:.4f}")
    
    print()


def cmd_list():
    """List all conversations."""
    print("Fetching conversations...\n")
    
    conversations = list_conversations()
    
    if not conversations:
        print("No conversations found.")
        return
    
    print(f"Found {len(conversations)} conversation(s):\n")
    
    for i, conv in enumerate(conversations, 1):
        print(f"Conversation {i}:")
        print_conversation_summary(conv)


def cmd_archive(conversation_id: str):
    """Archive a specific conversation."""
    print(f"Archiving conversation {conversation_id}...\n")
    
    # First, get conversation details
    try:
        conv = get_conversation(conversation_id)
        print("Conversation details:")
        print_conversation_summary(conv)
        
        sandbox_id = conv.get('sandbox_id')
        if sandbox_id:
            print(f"This will delete the sandbox '{sandbox_id}' and release its PVC.")
        
    except requests.exceptions.HTTPException as e:
        if e.response.status_code == 404:
            print(f"Warning: Conversation {conversation_id} not found (may already be deleted)")
        else:
            raise
    
    # Confirm deletion
    confirm = input("\nAre you sure you want to delete this conversation? (yes/no): ")
    if confirm.lower() != "yes":
        print("Cancelled.")
        return
    
    # Delete the conversation
    try:
        result = delete_conversation(conversation_id)
        print(f"\n✓ Successfully deleted conversation {conversation_id}")
        print(f"Response: {result}")
        print("\nThe sandbox and its PVC have been cleaned up (if no other conversations use it).")
    except requests.exceptions.HTTPException as e:
        if e.response.status_code == 404:
            print(f"Conversation {conversation_id} not found (may already be deleted)")
        else:
            print(f"Error deleting conversation: {e}")
            raise


def cmd_cleanup():
    """Archive all stopped conversations."""
    print("Fetching conversations...\n")
    
    conversations = list_conversations()
    
    # Filter to stopped conversations only
    stopped = [
        conv for conv in conversations
        if conv.get('sandbox_status') == 'STOPPED' or conv.get('execution_status') == 'stopped'
    ]
    
    if not stopped:
        print("No stopped conversations found to clean up.")
        return
    
    print(f"Found {len(stopped)} stopped conversation(s) to clean up:\n")
    
    for i, conv in enumerate(stopped, 1):
        print(f"{i}. {conv.get('title')} ({conv.get('id')})")
    
    print()
    confirm = input(f"Archive all {len(stopped)} stopped conversation(s)? (yes/no): ")
    if confirm.lower() != "yes":
        print("Cancelled.")
        return
    
    print()
    for conv in stopped:
        conv_id = conv.get('id')
        try:
            delete_conversation(conv_id)
            print(f"✓ Deleted conversation {conv_id} ({conv.get('title')})")
        except Exception as e:
            print(f"✗ Failed to delete conversation {conv_id}: {e}")
    
    print(f"\n✓ Cleanup complete. {len(stopped)} conversation(s) archived.")


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    
    command = sys.argv[1]
    
    if command == "list":
        cmd_list()
    elif command == "archive":
        if len(sys.argv) < 3:
            print("Error: conversation_id required")
            print("Usage: python archive_sandbox.py archive <conversation_id>")
            sys.exit(1)
        cmd_archive(sys.argv[2])
    elif command == "cleanup":
        cmd_cleanup()
    else:
        print(f"Unknown command: {command}")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
