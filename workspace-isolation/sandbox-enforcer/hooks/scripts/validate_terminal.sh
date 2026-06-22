#!/bin/bash
# PreToolUse hook: Validate terminal commands stay within workspace
# Based on jpshackelford/lxa sandbox isolation hook

input=$(cat)

# Get workspace directory from environment (OPENHANDS_PROJECT_DIR or fall back to PWD)
workspace="${OPENHANDS_PROJECT_DIR:-$PWD}"

# Check for # read-only escape hatch (allows read operations outside workspace)
has_readonly=$(echo "$input" | grep -qi "#[[:space:]]*read-only" && echo "yes" || echo "no")

# Extract the command name (simplified - just get first word from command field)
command_field=$(echo "$input" | grep -o '"command"[[:space:]]*:[[:space:]]*"[^"]*"' | head -1)
full_command=$(echo "$command_field" | sed 's/"command"[[:space:]]*:[[:space:]]*"//' | sed 's/"$//')
cmd_name=$(echo "$full_command" | awk '{print $1}')

# Block navigation commands that try to leave workspace
if echo "$cmd_name" | grep -qE "^(cd|pushd|popd)$"; then
    # Extract the target directory
    target=$(echo "$full_command" | awk '{for(i=2;i<=NF;i++) printf $i" "; print ""}' | sed 's/[[:space:]]*$//')

    # Check if target starts with /, ~, or .. (absolute or parent paths)
    if echo "$target" | grep -qE "^(/|~|\.\.)" && [ "$has_readonly" != "yes" ]; then
        cat << EOF
{
  "decision": "deny",
  "reason": "🚧 WORKSPACE ISOLATION: Cannot navigate outside your workspace directory.

Your workspace: $workspace
Attempted: $cmd_name $target

All work must stay within the assigned workspace to avoid conflicts with other parallel conversations.

💡 Tip: Add '# read-only' to your prompt if you only need to READ files outside the workspace."
}
EOF
        exit 2
    fi
fi

# Block write commands that target paths outside workspace
if echo "$cmd_name" | grep -qE "^(rm|rmdir|mv|cp|chmod|chown|mkdir|touch|dd|ln)$"; then
    # Check if command contains absolute paths (/) or home paths (~)
    if echo "$full_command" | grep -qE "(/|~)" && [ "$has_readonly" != "yes" ]; then
        # Simple heuristic: if command has "/" and doesn't contain workspace path, it might be external
        if ! echo "$full_command" | grep -q "$workspace"; then
            cat << EOF
{
  "decision": "deny",
  "reason": "🚧 WORKSPACE ISOLATION: Cannot modify files outside your workspace directory.

Your workspace: $workspace
Command: $cmd_name

Write operations must target paths within the workspace to prevent interference with other conversations.

💡 Tip: Use relative paths, or add '# read-only' if you're only reading external files."
}
EOF
            exit 2
        fi
    fi
fi

# Check for write redirects outside workspace (>, >>)
if echo "$full_command" | grep -qE "[0-9]*>{1,2}[[:space:]]*(/|~)"; then
    if ! echo "$full_command" | grep -q "$workspace" && [ "$has_readonly" != "yes" ]; then
        cat << EOF
{
  "decision": "deny",
  "reason": "🚧 WORKSPACE ISOLATION: Cannot redirect output to files outside workspace.

Your workspace: $workspace
Command: $full_command

Output redirects must target paths within the workspace."
}
EOF
        exit 2
    fi
fi

# All checks passed - allow the command
exit 0
