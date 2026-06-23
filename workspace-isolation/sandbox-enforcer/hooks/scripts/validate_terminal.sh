#!/bin/sh
# PreToolUse hook (reference copy of the logic inlined in ../hooks.json)
# Validate terminal commands stay within the workspace.
input=$(cat)
workspace="${OPENHANDS_PROJECT_DIR:-$PWD}"

# Read-only escape hatch: "# read-only" anywhere in the command.
has_readonly=no
if echo "$input" | grep -qi "#[[:space:]]*read-only"; then
has_readonly=yes
fi

full_command=$(printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
cmd_name=$(printf '%s' "$full_command" | awk '{print $1}')

# Navigation out of the workspace.
if printf '%s' "$cmd_name" | grep -qE "^(cd|pushd|popd)$"; then
target=$(printf '%s' "$full_command" | awk '{$1=""; sub(/^ /,""); print}')
if printf '%s' "$target" | grep -qE "^(/|~|\.\.)" && [ "$has_readonly" != yes ]; then
cat <<EOF
{"decision": "deny", "reason": "🚧 WORKSPACE ISOLATION: Cannot navigate outside your workspace ($workspace). Attempted: $cmd_name $target. Add a # read-only comment to your command if you only need to READ outside the workspace."}
EOF
exit 2
fi
fi

# Write commands targeting an absolute/home path outside the workspace.
if printf '%s' "$cmd_name" | grep -qE "^(rm|rmdir|mv|cp|chmod|chown|mkdir|touch|dd|ln)$"; then
if printf '%s' "$full_command" | grep -qE "(^|[[:space:]])(/|~)" && [ "$has_readonly" != yes ]; then
if ! printf '%s' "$full_command" | grep -qF "$workspace"; then
cat <<EOF
{"decision": "deny", "reason": "🚧 WORKSPACE ISOLATION: Cannot modify files outside your workspace ($workspace). Command: $cmd_name. Use a path inside the workspace, or add a # read-only comment if you are only reading."}
EOF
exit 2
fi
fi
fi

# Output redirects to a path outside the workspace.
if printf '%s' "$full_command" | grep -qE "[0-9]*>{1,2}[[:space:]]*(/|~)"; then
if ! printf '%s' "$full_command" | grep -qF "$workspace" && [ "$has_readonly" != yes ]; then
cat <<EOF
{"decision": "deny", "reason": "🚧 WORKSPACE ISOLATION: Cannot redirect output to a file outside your workspace ($workspace)."}
EOF
exit 2
fi
fi

exit 0
