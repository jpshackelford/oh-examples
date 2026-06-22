# Workspace Isolation with Hooks (Advanced)

An **advanced** hook example that enforces workspace isolation - preventing agents from navigating or writing outside their assigned directory. This is particularly useful when running **multiple parallel conversations on a local machine**, ensuring each conversation stays in its own sandbox without interfering with others.

Based on the production implementation in [jpshackelford/lxa](https://github.com/jpshackelford/lxa/blob/main/src/hooks/sandbox.py).

## What's in the Box

The [`sandbox-enforcer/`](./sandbox-enforcer/) plugin bundles:

- **Hook scripts** (`hooks/scripts/*.sh`) - Bash scripts that validate terminal and file_editor operations
- **Hooks manifest** (`hooks/hooks.json`) - Configures PreToolUse hooks
- **Skill** (`skills/sandbox-enforcer/SKILL.md`) - Documentation about isolation rules
- **Plugin manifest** (`.claude-plugin/plugin.json`) - Standard Claude Code plugin format

## The Problem This Solves

**Scenario:** You're running a local OpenHands instance with multiple conversations in parallel:

```
~/my-projects/
├── web-app/      ← Conversation 1: "Refactor the auth module"
├── api-server/   ← Conversation 2: "Add rate limiting"
└── cli-tool/     ← Conversation 3: "Fix the parser bug"
```

**Without workspace isolation:**
- Agent 1 might accidentally `cd ../api-server` and modify the wrong project
- Agent 2 could `rm -rf ../web-app/node_modules` while cleaning up
- Agent 3 might write test output to `/tmp` that conflicts with other agents

**With workspace isolation:**
- Each agent stays in its assigned directory
- Attempts to navigate or write outside are blocked with helpful messages
- Agents can still READ external files (with `# read-only` escape hatch)

## How It Works

```
User to Agent 1: "Navigate to /tmp and create a cache file"
  ↓
Agent 1: *prepares: cd /tmp*
  ↓
PreToolUse Hook (terminal): *intercepts command*
  ├─ Detects: cd /tmp (outside workspace)
  ├─ Workspace: /home/user/my-projects/web-app
  └─ Returns exit code 2 (block) + message
  ↓
Agent 1: *receives block, explains to user*
  ↓
User: *Agent stays safely in web-app directory*
```

Meanwhile, Agent 2 and Agent 3 work independently in their own workspaces without risk of collision.

## Protected Operations

The plugin enforces isolation for:

### Terminal Commands
- **Navigation:** `cd`, `pushd`, `popd` to external directories
- **Write operations:** `rm`, `mv`, `cp`, `chmod`, `mkdir`, `touch`, `dd`, `ln`, etc.
- **Output redirection:** `>`, `>>` to external paths

### File Editor Operations
- **Write commands:** `create`, `str_replace`, `insert`, `undo_edit` to external paths
- **Read commands:** `view` is always allowed (can read anywhere)

## Try It

### Local Development Setup

1. Create multiple project directories:
```bash
mkdir -p ~/my-projects/{project-a,project-b,project-c}
```

2. Load the plugin in each conversation with different workspace dirs:
```bash
# Conversation 1 - workspace: ~/my-projects/project-a
cd ~/my-projects/project-a
# Load plugin with load-plugin example

# Conversation 2 - workspace: ~/my-projects/project-b
cd ~/my-projects/project-b
# Load plugin with load-plugin example
```

3. Try cross-contamination (it will be blocked):
```bash
# In Conversation 1
cd ../project-b  # BLOCKED
cp file.txt ../project-b/  # BLOCKED
```

### Via API

```bash
cd ../load-plugin

# This will be blocked (cd outside workspace)
python load_plugin.py \
  --repo-path workspace-isolation/sandbox-enforcer \
  --message "Navigate to /tmp and list files there"

# This will be allowed (within workspace)
python load_plugin.py \
  --repo-path workspace-isolation/sandbox-enforcer \
  --message "List all files in the current directory"
```

### Via Badge

[![Try Sandbox Enforcer](https://img.shields.io/badge/Try%20Sandbox%20Enforcer-blue)](https://app.all-hands.dev/launch?plugins=W3sic291cmNlIjogImdpdGh1YjpqcHNoYWNrZWxmb3JkL29oLWV4YW1wbGVzIiwgInJlZiI6ICJtYWluIiwgInJlcG9fcGF0aCI6ICJ3b3Jrc3BhY2UtaXNvbGF0aW9uL3NhbmRib3gtZW5mb3JjZXIifV0%3D&message=Navigate%20to%20%2Ftmp%20and%20create%20a%20file%20there)

> **Note:** In cloud ephemeral workspaces, this isolation is less critical (each conversation gets its own container), but it still demonstrates the technique for local setups.

## The `# read-only` Escape Hatch

Sometimes you need to READ system files or shared resources outside your workspace.

Add `# read-only` to your prompt:

```bash
# ✓ Allowed - read-only access to system file
cat /etc/os-release  # read-only

# ✓ Allowed - check system information
uname -a  # read-only

# ✗ Still blocked - write operation
echo "data" > /tmp/output.txt  # read-only  (doesn't help with writes)
```

The hook detects the `# read-only` comment and allows non-destructive operations that reference external paths.

## Hook Scripts

### 1. Terminal Validation (`validate_terminal.sh`)

Checks terminal commands for:
- Navigation commands (`cd`, `pushd`, `popd`) trying to leave workspace
- Write commands (`rm`, `mv`, `cp`, `chmod`, `mkdir`, etc.) targeting external paths
- Output redirects (`>`, `>>`) to external files

```bash
#!/bin/bash
input=$(cat)
workspace="${OPENHANDS_PROJECT_DIR:-$PWD}"

# Check for navigation outside workspace
if [[ command is cd/pushd/popd to external path ]]; then
    echo '{"decision": "deny", "reason": "Cannot navigate outside workspace..."}'
    exit 2
fi

# Check for write operations outside workspace
# ...
```

### 2. File Editor Validation (`validate_file_editor.sh`)

Checks file_editor operations:
- Always allows `view` (read-only)
- Blocks `create`, `str_replace`, `insert`, `undo_edit` to external paths

```bash
#!/bin/bash
input=$(cat)
workspace="${OPENHANDS_PROJECT_DIR:-$PWD}"

# Always allow view
if [[ command == "view" ]]; then
    exit 0
fi

# Block writes outside workspace
# ...
```

## Workspace Detection

The hooks determine your workspace using (in order):

1. **`OPENHANDS_PROJECT_DIR`** - Set by OpenHands Cloud/Enterprise
2. **`PWD`** - Current working directory (fallback)

This makes it work in both local and cloud environments.

## Plugin Structure

```
sandbox-enforcer/
├── .claude-plugin/
│   └── plugin.json              # Plugin metadata
├── hooks/
│   ├── hooks.json               # Hook configuration (references scripts)
│   └── scripts/
│       ├── validate_terminal.sh     # Terminal command validation
│       └── validate_file_editor.sh  # File editor validation
└── skills/
    └── sandbox-enforcer/
        └── SKILL.md             # Documentation (auto-loaded)
```

This follows the **Claude Code plugin format** with external script files for better maintainability.

## Comparison with Other Examples

| Example | Approach | Security Level | Use Case | Complexity |
|---------|----------|----------------|----------|------------|
| [command-blacklist](../command-blacklist/) | Block dangerous patterns | Medium | General protection | Simple |
| [command-whitelist](../command-whitelist/) | Allow only approved commands | High | Read-only, educational | Simple |
| **workspace-isolation** (this) | Enforce directory boundaries | High | Parallel conversations, multi-tenant | **Advanced** |

All three can be combined for defense-in-depth!

## When to Use This

**✅ Use workspace isolation when:**
- Running multiple parallel conversations on one machine
- Each conversation works on a different project/directory
- You need to prevent cross-contamination between workspaces
- Building multi-tenant local development environments
- Teaching/educational scenarios with multiple students

**⏭️ Skip workspace isolation when:**
- Using cloud ephemeral workspaces (already isolated by containers)
- Running only one conversation at a time
- The agent needs to work across multiple project directories intentionally

## Real-World Example: LXA

This example is based on [jpshackelford/lxa](https://github.com/jpshackelford/lxa), a production tool that manages multiple OpenHands conversations in parallel:

```
lxa schedule --all  # Process all jobs in parallel, each in its own workspace
├── Job 1: /data/job-1234/  (isolated)
├── Job 2: /data/job-5678/  (isolated)
└── Job 3: /data/job-9012/  (isolated)
```

The hooks ensure each job stays in its assigned directory, preventing interference.

## Limitations

This is a **simplified, heuristic-based implementation** with limitations:

1. **No full shell parsing** - Complex quoting might bypass detection
2. **No path canonicalization** - Doesn't resolve symlinks or `.` / `..` fully
3. **Simplified command extraction** - May not catch all edge cases
4. **Fails open** - If hook can't parse input, it allows the operation (for safety)

For production use, see the full [Python implementation in lxa](https://github.com/jpshackelford/lxa/blob/main/src/hooks/sandbox.py) which handles:
- Full path resolution with `pathlib`
- Symlink following
- Complex shell command parsing with `shlex`
- Proper handling of shell metacharacters and quoting

## Extending the Example

Want to add more restrictions? Edit the script files:

```bash
# In validate_terminal.sh, add more blocked commands:
if echo "$cmd_name" | grep -qE "^(rm|rmdir|mv|cp|chmod|chown|mkdir|touch|dd|ln|npm|pip)$"; then
    # Block npm and pip too
    ...
fi
```

External scripts are easier to maintain than inline JSON-escaped bash!

## Related

- [OpenHands Hooks Guide](https://docs.openhands.dev/sdk/guides/hooks.md) - Official documentation
- [jpshackelford/lxa](https://github.com/jpshackelford/lxa) - Production implementation
- [command-blacklist](../command-blacklist/) - Block dangerous commands
- [command-whitelist](../command-whitelist/) - Whitelist safe commands
- [`load-plugin`](../load-plugin/) - How to load this plugin
- [`launch-plugin-badge`](../launch-plugin-badge/) - No-code launcher

## Contributing

This example prioritizes clarity and accessibility over completeness. If you're building a production system, refer to the [lxa implementation](https://github.com/jpshackelford/lxa/blob/main/src/hooks/sandbox.py) for a more robust approach.
