---
description: Enforces workspace isolation - prevents navigation and writes outside assigned directory
triggers:
  - workspace
  - isolation
  - sandbox
---

# Sandbox Enforcer Skill

This skill works automatically through PreToolUse hooks - you don't need to invoke it directly.

## What It Does

The Sandbox Enforcer plugin provides **workspace isolation** for agents, preventing them from:

1. **Navigating** outside their assigned workspace (`cd`, `pushd`, `popd`)
2. **Writing** files outside the workspace (`cp`, `mv`, `rm`, `mkdir`, `touch`, etc.)
3. **Redirecting** output to external paths (`>`, `>>`)
4. **Editing** files outside the workspace (file_editor tool)

This is particularly useful when running **multiple parallel conversations** on a local machine - each conversation stays in its own directory and can't interfere with others.

## Use Cases

### 🏢 Multi-Tenant Local Development
Run multiple agent conversations in parallel, each working on different projects:
```
~/projects/
├── project-a/  ← Agent 1 works here (isolated)
├── project-b/  ← Agent 2 works here (isolated)
└── project-c/  ← Agent 3 works here (isolated)
```

### 🎓 Educational Environments
Give students separate workspaces - they can't accidentally affect each other's files.

### 🧪 Testing & Experiments
Run experimental agents without risking damage to other directories.

### 🔒 Security-Sensitive Workflows
Ensure agents can only modify their designated areas.

## How It Works

The plugin uses **two PreToolUse hooks**:

### 1. Terminal Hook (`validate_terminal.sh`)
Intercepts `terminal` tool commands and checks:
- **Navigation**: Blocks `cd /other/path`, `pushd ~/elsewhere`, `popd` to external dirs
- **Write commands**: Blocks `rm /tmp/file`, `cp file.txt /other/`, `mkdir /external/`
- **Redirects**: Blocks `echo "data" > /tmp/output.txt`

### 2. File Editor Hook (`validate_file_editor.sh`)
Intercepts `file_editor` tool operations and:
- **Allows**: `view` commands (read-only) to any path
- **Blocks**: `create`, `str_replace`, `insert`, `undo_edit` to paths outside workspace

## The `# read-only` Escape Hatch

Sometimes you need to READ files outside your workspace (system configs, shared libraries, etc.).

Add `# read-only` to your prompt to tell the hook you're only reading:

```bash
# ✓ Allowed - read-only escape hatch
cat /etc/os-release  # read-only

# ✗ Blocked - write operation
echo "data" > /tmp/output.txt  # read-only  (the read-only comment doesn't help here)
```

The hook detects the `# read-only` comment and allows the operation even if it references external paths - **but only if the command itself is non-destructive**.

## Protected Operations

| Operation | Example | Blocked? | Why |
|-----------|---------|----------|-----|
| Navigate out | `cd /tmp` | ✗ Yes | Leaves workspace |
| Navigate in | `cd subdir` | ✓ No | Within workspace |
| Write external | `rm /tmp/file` | ✗ Yes | External write |
| Write internal | `touch newfile.txt` | ✓ No | Within workspace |
| Redirect external | `echo x > /tmp/f` | ✗ Yes | External write |
| Redirect internal | `echo x > output.txt` | ✓ No | Within workspace |
| View external | `cat /etc/hosts` | ⚠️ Depends | Allowed with `# read-only` |
| Edit external | `file_editor create /tmp/f.txt` | ✗ Yes | External write |
| View any | `file_editor view /etc/hosts` | ✓ Always | Read-only command |

## Workspace Detection

The hook uses these methods to determine your workspace (in order):

1. **`OPENHANDS_PROJECT_DIR`** environment variable (set by OpenHands)
2. **`PWD`** - current working directory (fallback)

## Example Blocks

### Navigation Block
```
User: Navigate to /tmp and create a file there
Agent: *attempts cd /tmp*
Hook: 🚧 Blocks with:
"Cannot navigate outside your workspace directory.
Your workspace: /home/user/project-a
Attempted: cd /tmp
All work must stay within the assigned workspace..."
```

### Write Block
```
User: Copy this file to /tmp
Agent: *attempts cp file.txt /tmp/*
Hook: 🚧 Blocks with:
"Cannot modify files outside your workspace directory.
Your workspace: /home/user/project-a
Command: cp
Write operations must target paths within the workspace..."
```

### File Editor Block
```
User: Edit /etc/hosts
Agent: *attempts file_editor str_replace /etc/hosts*
Hook: 🚧 Blocks with:
"file_editor command blocked - targets path outside workspace.
Command: str_replace
Path: /etc/hosts
Your workspace: /home/user/project-a
Write operations to paths outside workspace are NOT allowed..."
```

## Allowed Operations

Within your workspace, everything works normally:
- `mkdir newdir`
- `touch newfile.txt`
- `cd subdir`
- `echo "data" > output.txt`
- `file_editor create myfile.py`

## Limitations

This is a **heuristic-based hook** with some limitations:

1. **Path detection is simplified** - complex shell quoting might bypass detection
2. **No actual path resolution** - doesn't resolve symlinks or canonicalize paths
3. **Command parsing is basic** - doesn't handle all shell syntax edge cases
4. **Read operations aren't fully restricted** - agents can read files outside workspace (use `# read-only`)

For production use, consider the full Python-based implementation in [jpshackelford/lxa](https://github.com/jpshackelford/lxa/blob/main/src/hooks/sandbox.py) which handles symlinks, path resolution, and more complex scenarios.

## Technical Details

- **Hook Type:** PreToolUse (runs before both `terminal` and `file_editor` tools)
- **Matcher:** `terminal` and `file_editor`
- **Type:** External script files (`.sh`)
- **Exit Codes:**
  - `0` = Allow operation
  - `2` = Block operation (with reason)
- **Timeout:** 5 seconds per hook
- **Workspace variable:** `OPENHANDS_PROJECT_DIR` or `PWD`

## Based On

This example is inspired by the production-grade sandbox isolation hook in [jpshackelford/lxa](https://github.com/jpshackelford/lxa), which uses Python for more robust path resolution and validation.
