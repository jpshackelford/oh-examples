---
description: Enforces strict command whitelist - only allows approved read-only operations
triggers:
  - strict mode
  - whitelist
  - restricted
---

# Strict Mode Skill

This skill works automatically through PreToolUse hooks - you don't need to invoke it directly.

## What It Does

The Strict Mode plugin implements a **whitelist approach** to command execution:

- ✅ **Allows** only explicitly approved commands
- ❌ **Blocks** everything else (deny by default)
- 🔒 **Focuses** on read-only operations for safety

This is the opposite of the blacklist approach (which allows everything except known dangerous patterns).

## Whitelisted Commands

Only these commands are allowed:

### File Operations (Read-Only)
- `ls` - List directory contents
- `cat` - View file contents
- `head` - View beginning of files
- `tail` - View end of files
- `file` - Determine file type

### Search & Filter
- `grep` - Search text patterns
- `find` - Search for files
- `wc` - Count words/lines/bytes

### System Information
- `pwd` - Print working directory
- `whoami` - Current user
- `date` - Current date/time
- `uname` - System information
- `df` - Disk space
- `du` - Disk usage
- `stat` - File statistics

### Other Utilities
- `echo` - Print text
- `which` - Locate command
- `env` - Show environment variables
- `printenv` - Print environment
- `history` - Command history
- `tree` - Directory tree view

## Blocked Commands

Everything not on the whitelist is blocked, including:

- ❌ File modifications: `rm`, `mv`, `cp`, `touch`, `mkdir`, `rmdir`
- ❌ Package managers: `pip`, `npm`, `apt`, `yum`, `brew`
- ❌ Editors: `vim`, `nano`, `emacs`
- ❌ Network tools: `curl`, `wget`, `ssh`, `scp`
- ❌ Process management: `kill`, `pkill`, `killall`
- ❌ And many more...

## How It Works

When you ask me to execute a shell command, the plugin's PreToolUse hook:

1. Extracts the command name from the terminal action
2. Checks if it's in the whitelist
3. If **YES**: Returns `exit 0` (allow)
4. If **NO**: Returns `exit 2` with explanation (block)

## Example Interactions

**Allowed (in whitelist):**
```
User: List files in the current directory
Agent: *executes ls -la*
Hook: ✓ Allows (ls is whitelisted)
```

**Blocked (not in whitelist):**
```
User: Install the requests package with pip
Agent: *attempts pip install requests*
Hook: 🔒 Blocks with: "The command 'pip' is not in the whitelist..."
```

## When to Use Strict Mode

**Good for:**
- 🎓 **Educational** environments (learn safely)
- 🔍 **Read-only** analysis tasks
- 🤝 **Untrusted** agents or users
- 📊 **Auditing** existing systems
- 🛡️ **Maximum** security requirements

**Not ideal for:**
- 🚀 **Development** work (too restrictive)
- 📝 **Content creation** (can't write files)
- 🔧 **System administration** (needs full access)
- 🏗️ **Building** projects (needs write operations)

## Extending the Whitelist

To allow additional commands, edit [`hooks/hooks.json`](../../hooks/hooks.json) and add them to the `allowed_commands` list:

```bash
allowed_commands="
ls
cat
# ... existing commands ...
git        # Add git commands
python     # Add python execution
"
```

## Blacklist vs. Whitelist

| Approach | Blocks | Allows | Security | Usability |
|----------|--------|--------|----------|-----------|
| **Blacklist** ([`command-blacklist`](../../command-blacklist/)) | Known dangerous patterns | Everything else | ⚠️ Medium | ✅ High |
| **Whitelist** (this example) | Everything by default | Only approved commands | ✅ High | ⚠️ Medium |

Choose based on your use case:
- **Blacklist** = General protection with full functionality
- **Whitelist** = Maximum security with limited functionality

## Technical Details

- **Hook Type:** PreToolUse (runs before terminal tool execution)
- **Matcher:** `terminal` (only applies to terminal/shell commands)
- **Exit Codes:**
  - `0` = Allow command (in whitelist)
  - `2` = Block command (not in whitelist)
- **Timeout:** 5 seconds
- **Approach:** Deny-by-default (whitelist)

The hook extracts the command name and checks it against a hardcoded list. Commands not in the list are blocked with a helpful error message listing all allowed commands.
