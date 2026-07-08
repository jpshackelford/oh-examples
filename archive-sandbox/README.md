# Archive Sandbox to Release PVC

This example demonstrates how to properly archive/delete OpenHands conversations to release their Persistent Volume Claims (PVCs) and free up storage resources.

## Overview

When you create an OpenHands conversation, the system provisions a **sandbox** (also called a "runtime") that includes:

- **Kubernetes Pod** - Container running the agent-server
- **Kubernetes Service** - Network access to the pod
- **Persistent Volume Claim (PVC)** - Storage for the workspace files
- **Ingress/HTTPRoute** - External routing
- **ServiceAccount, PodDisruptionBudget** - Supporting K8s resources

The PVC persists even when a conversation is paused or stopped, allowing you to resume work later. However, PVCs consume storage quota and incur costs. To release these resources, you need to **delete the conversation**, which triggers full sandbox cleanup.

## How Sandbox Cleanup Works

Based on the [runtime-api](https://github.com/All-Hands-AI/runtime-api) implementation, here's what happens when you delete a conversation:

### 1. Conversation Deletion (`DELETE /api/v1/app-conversations/{conversation_id}`)

The OpenHands Cloud API:
- Marks the conversation as deleted in the database
- Checks if any other conversations share the same sandbox
- If no other conversations use the sandbox, triggers sandbox cleanup

### 2. Sandbox Cleanup (Runtime API)

The runtime API's `delete_runtime_and_workspace_in_k8s()` function removes all Kubernetes resources:

```python
# From runtime-api/k8s.py
def delete_runtime_and_workspace_in_k8s(runtime_id, pod_id: str | None = None):
    """Delete all K8s resources for a runtime."""
    
    # Resources deleted in order:
    # 1. Deployment
    # 2. ServiceAccount
    # 3. Service
    # 4. PersistentVolumeClaim  ← This releases the storage!
    # 5. PodDisruptionBudget
    # 6. HTTPRoute/Ingress
    # 7. VolumeSnapshot (if any)
```

**Key Point**: The PVC deletion is what actually releases the storage. Once the PVC is deleted:
- The underlying PersistentVolume (PV) is freed
- Storage quota is released
- Associated costs stop accumulating

### 3. Resource Lifecycle States

| State | Pod | PVC | Storage Released? |
|-------|-----|-----|-------------------|
| **RUNNING** | ✅ Running | ✅ Exists | ❌ No |
| **PAUSED** | ❌ Scaled to 0 | ✅ Exists | ❌ No |
| **STOPPED** | ❌ Deleted | ✅ Exists* | ❌ No |
| **DELETED** | ❌ Deleted | ❌ Deleted | ✅ **Yes** |

\* For standard (non-fuse) runtimes, the PVC persists when stopped to allow resuming. A VolumeSnapshot may be taken before deletion for archival purposes.

## Important Concepts

### Warm Runtimes and PVC Types

OpenHands supports two types of sandboxes:

#### Standard (PVC-backed)
- PVC provisioned at startup
- Workspace stored on persistent disk
- PVC persists through pause/resume
- **Must delete conversation to release PVC**

#### Fuse/Dormant (S3-backed)
- No PVC provisioned
- Workspace stored in S3 via fusey
- Mounted dynamically at claim time
- Fast resume without PVC snapshots
- **No PVC cleanup needed** - just deletes S3 objects

### Cleanup Cronjob

The runtime-api runs a cleanup cronjob (`cleanup.py`) every 5 minutes that:

1. **Cleanup stuck PVCs** - Removes PVCs that never bound
2. **Cleanup terminated pods** - Removes pods with no DB record
3. **Pause idle runtimes** - Pauses runtimes idle > 30 min (configurable)
4. **Snapshot and delete idle PVCs** - For paused standard runtimes
5. **Delete old fuse workspaces** - Purges S3 objects for stopped fuse runtimes > 30 days
6. **Delete old runtimes** - Removes K8s resources for runtimes stopped > 1 day

**Important**: The cleanup cronjob does NOT delete PVCs for active or recently stopped conversations. You must explicitly delete the conversation to trigger immediate cleanup.

## Files in This Example

- **`archive_sandbox.py`** - Main CLI tool for archiving conversations
- **`example_create_and_archive.py`** - Complete workflow demonstration
- **`requirements.txt`** - Python dependencies
- **`README.md`** - This documentation

## Usage

### Prerequisites

```bash
# Set your OpenHands API key
export OH_API_KEY="your-api-key-here"

# Install dependencies
pip install -r requirements.txt
# or
pip install requests
```

### Quick Start: Complete Workflow Demo

Run the complete workflow example to see the entire process:

```bash
python example_create_and_archive.py
```

This will:
1. Create a new test conversation (provisions sandbox + PVC)
2. Show conversation details (sandbox_id, status, etc.)
3. Ask for confirmation to archive
4. Delete the conversation (releases PVC)
5. Verify deletion

Perfect for understanding the complete lifecycle!

### List All Conversations

```bash
python archive_sandbox.py list
```

Output shows conversation details including:
- Conversation ID
- Title
- Sandbox ID (the runtime ID)
- Status (RUNNING, STOPPED, etc.)
- Cost metrics

### Archive a Specific Conversation

```bash
python archive_sandbox.py archive <conversation_id>
```

This will:
1. Show conversation details
2. Ask for confirmation
3. Delete the conversation
4. Trigger sandbox cleanup (if no other conversations use it)
5. Release the PVC

Example:
```bash
$ python archive_sandbox.py archive abc123def456

Archiving conversation abc123def456...

Conversation details:
  ID: abc123def456
  Title: My Test Conversation
  Sandbox ID: m9dEVO2bDqar86rIaix93
  Sandbox Status: STOPPED
  Execution Status: stopped
  Created: 2024-01-15T10:30:00Z
  Updated: 2024-01-15T11:45:00Z
  Cost: $0.4339

This will delete the sandbox 'm9dEVO2bDqar86rIaix93' and release its PVC.

Are you sure you want to delete this conversation? (yes/no): yes

✓ Successfully deleted conversation abc123def456
Response: {'success': True}

The sandbox and its PVC have been cleaned up (if no other conversations use it).
```

### Bulk Cleanup Stopped Conversations

```bash
python archive_sandbox.py cleanup
```

This will:
1. Find all stopped conversations
2. Show a summary
3. Ask for confirmation
4. Archive all stopped conversations
5. Release their PVCs

This is useful for cleaning up after testing or development.

## Best Practices

### When to Archive

✅ **Do archive**:
- Test conversations you no longer need
- Failed or error conversations
- Completed one-off tasks
- Conversations stopped for > 7 days

❌ **Don't archive**:
- Active conversations (status: RUNNING)
- Conversations you plan to resume soon
- Conversations with important work not yet backed up

### Before Archiving

1. **Download important files** from the workspace
2. **Export conversation history** if needed (use the download endpoint)
3. **Check for workspace archives** - OpenHands may automatically archive workspaces before pause (see `tags.archiveworkspacepath`)

### Workspace Archiving (Automatic)

OpenHands can automatically archive workspace contents before pausing/stopping:

```python
# Environment variable controls this feature
RUNTIME_FILE_ARCHIVE_ENABLED=true  # Enable workspace archiving
RUNTIME_FILE_ARCHIVE_FORMATS=tar.gz,git-delta  # Archive formats
RUNTIME_FILE_ARCHIVE_PREFIX=workspace-archives  # S3 prefix
```

If enabled, the cleanup process will:
1. Download workspace as tar.gz or git-delta
2. Upload to S3 with manifest
3. Tag conversation with archive path
4. Then delete the PVC

Check `conversation.tags.archiveworkspacepath` to see if an archive exists.

## Monitoring and Verification

### Check Kubernetes Resources

If you have kubectl access to the runtime cluster:

```bash
# List all runtime pods
kubectl get pods -n runtime-pods

# List all PVCs
kubectl get pvc -n runtime-pods

# Check a specific runtime's resources
kubectl get all,pvc -n runtime-pods -l runtime_id=<sandbox_id>
```

After deleting a conversation, these resources should be removed.

### Check via API

```bash
# List your conversations
curl -H "Authorization: Bearer $OH_API_KEY" \
  "https://app.all-hands.dev/api/v1/app-conversations/search?limit=100" | jq

# Get specific conversation (returns 404 if deleted)
curl -H "Authorization: Bearer $OH_API_KEY" \
  "https://app.all-hands.dev/api/v1/app-conversations/<conversation_id>" | jq
```

## Example: Full Workflow

Here's a complete example of creating and archiving a sandbox:

```python
import os
import requests

API_BASE = "https://app.all-hands.dev"
API_KEY = os.getenv("OH_API_KEY")
headers = {"Authorization": f"Bearer {API_KEY}"}

# 1. Create a conversation (creates sandbox automatically)
response = requests.post(
    f"{API_BASE}/api/v1/app-conversations/stream-start",
    headers=headers,
    json={
        "llm_model": "claude-sonnet-4-5-20250929",
        "agent_kind": "openhands",
    }
)
conv_data = response.json()
conversation_id = conv_data["id"]
sandbox_id = conv_data["sandbox_id"]

print(f"Created conversation {conversation_id}")
print(f"Sandbox ID: {sandbox_id}")

# 2. Do some work...
# (send messages, run commands, etc.)

# 3. Archive when done
response = requests.delete(
    f"{API_BASE}/api/v1/app-conversations/{conversation_id}",
    headers=headers
)

print(f"Archived conversation {conversation_id}")
print(f"PVC for sandbox {sandbox_id} has been released")
```

## Troubleshooting

### "Conversation not found" error

The conversation may already be deleted. This is safe to ignore.

### PVC still exists after deletion

Possible reasons:
1. **Another conversation uses the same sandbox** - The sandbox is shared
2. **Cleanup not yet run** - K8s deletion is asynchronous, may take a few seconds
3. **Kubernetes finalizers** - PV/PVC may have finalizers delaying deletion

Check:
```bash
kubectl get pvc -n runtime-pods -o yaml | grep -A 5 finalizers
```

### Can't delete running conversation

You can delete running conversations - the API will stop them first. However, it's cleaner to stop them explicitly:

```bash
# Stop first (optional)
curl -X POST \
  -H "Authorization: Bearer $OH_API_KEY" \
  "https://app.all-hands.dev/api/organizations/<org_id>/conversations/<conv_id>/stop"

# Then delete
python archive_sandbox.py archive <conversation_id>
```

## Related Resources

- [OpenHands Runtime API](https://github.com/All-Hands-AI/runtime-api) - The service managing sandboxes
- [OpenHands Cloud API Documentation](https://app.all-hands.dev/openapi.json) - Full API reference
- [Kubernetes PVC Documentation](https://kubernetes.io/docs/concepts/storage/persistent-volumes/)

## Summary

**Key Takeaways**:

1. ✅ **Deleting a conversation releases its PVC** - This is the primary way to free storage
2. ✅ **Pausing/Stopping preserves the PVC** - For resuming work later
3. ✅ **Use the cleanup command** - Bulk archive stopped conversations
4. ✅ **Automatic workspace archiving** - May preserve files before PVC deletion
5. ✅ **Check before deleting** - Download important files first

When in doubt, remember: **DELETE conversation → Cleanup sandbox → Release PVC → Free storage** ✨
