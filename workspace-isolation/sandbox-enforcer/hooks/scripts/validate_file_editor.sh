#!/bin/bash
# PreToolUse hook: Validate file_editor operations stay within workspace
# Based on jpshackelford/lxa sandbox isolation hook

input=$(cat)

# Get workspace directory from environment
workspace="${OPENHANDS_PROJECT_DIR:-$PWD}"

# Extract the command (view, create, str_replace, insert, undo_edit)
cmd=$(echo "$input" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"command"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')

# View command is always allowed (read-only)
if [ "$cmd" = "view" ]; then
    exit 0
fi

# For write commands, validate the path is within workspace
if echo "$cmd" | grep -qE "^(create|str_replace|insert|undo_edit)$"; then
    # Extract the path
    path=$(echo "$input" | grep -o '"path"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1 | sed 's/"path"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')

    # Empty path - block with error
    if [ -z "$path" ]; then
        cat << EOF
{
  "decision": "deny",
  "reason": "🚧 WORKSPACE ISOLATION: file_editor command '$cmd' requires a path."
}
EOF
        exit 2
    fi

    # Check if path is absolute and outside workspace
    if echo "$path" | grep -q "^/"; then
        # Absolute path - check if it's within workspace
        if ! echo "$path" | grep -q "^$workspace"; then
            cat << EOF
{
  "decision": "deny",
  "reason": "🚧 WORKSPACE ISOLATION: file_editor command blocked - targets path outside workspace.

Command: $cmd
Path: $path
Your workspace: $workspace

Write operations (create, str_replace, insert, undo_edit) to paths outside the workspace are NOT allowed.

💡 Tip: Use relative paths within your workspace, or 'view' for read-only access."
}
EOF
            exit 2
        fi
    fi

    # Check if path tries to escape with ../
    if echo "$path" | grep -qE "(^|/)\\.\\./"; then
        # This is a simplistic check - a proper implementation would resolve the path
        # For now, warn about potentially suspicious paths
        cat << EOF
{
  "decision": "deny",
  "reason": "🚧 WORKSPACE ISOLATION: Suspicious path detected with parent directory references (..).

Command: $cmd
Path: $path
Your workspace: $workspace

Paths using '..' may escape the workspace boundary and are blocked.

💡 Tip: Use absolute paths within workspace or simple relative paths."
}
EOF
        exit 2
    fi
fi

# All checks passed - allow the operation
exit 0
