#!/bin/sh
# PreToolUse hook (reference copy of the logic inlined in ../hooks.json)
# Validate file_editor operations stay within the workspace.
input=$(cat)
workspace="${OPENHANDS_PROJECT_DIR:-$PWD}"

# Escape a value so it can be interpolated into a JSON string literal without
# producing invalid JSON (a stray " or \ in the path would otherwise break the
# {"decision":"deny","reason":"..."} payload and drop the reason).
json_escape() {
printf '%s' "$1" | sed 's/\\/\\\\/g; s/"/\\"/g'
}

cmd=$(printf '%s' "$input" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)

# view is read-only and always allowed.
if [ "$cmd" = view ]; then
exit 0
fi

if printf '%s' "$cmd" | grep -qE "^(create|str_replace|insert|undo_edit)$"; then
path=$(printf '%s' "$input" | sed -n 's/.*"path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -n1)
path=${path%\\}
ws=$(json_escape "$workspace")
c=$(json_escape "$cmd")
p=$(json_escape "$path")

if [ -z "$path" ]; then
cat <<EOF
{"decision": "deny", "reason": "🚧 WORKSPACE ISOLATION: file_editor command $c requires a path."}
EOF
exit 2
fi

# Absolute path must be inside the workspace.
case "$path" in
/*)
case "$path" in
"$workspace"|"$workspace"/*) : ;;
*)
cat <<EOF
{"decision": "deny", "reason": "🚧 WORKSPACE ISOLATION: file_editor $c blocked - path $p is outside your workspace ($ws). Use a path inside the workspace, or use view for read-only access."}
EOF
exit 2
;;
esac
;;
esac

# Reject parent-directory traversal.
case "$path" in
../*|*/../*|*/..)
cat <<EOF
{"decision": "deny", "reason": "🚧 WORKSPACE ISOLATION: file_editor $c blocked - path $p uses parent-directory (..) traversal which may escape the workspace."}
EOF
exit 2
;;
esac
fi

exit 0
