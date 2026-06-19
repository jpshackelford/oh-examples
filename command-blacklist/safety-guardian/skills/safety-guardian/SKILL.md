---
description: Automatically protects against dangerous shell commands using hooks
triggers:
  - dangerous command
  - blocked command
  - safety
---

# Safety Guardian Skill

This skill works automatically through PreToolUse hooks - you don't need to invoke it directly.

## What It Does

The Safety Guardian plugin protects you from accidentally executing dangerous shell commands by:

1. **Blocking destructive rm -rf commands** targeting system directories
2. **Preventing chmod 777** on sensitive directories
3. **Stopping dd operations** on raw block devices
4. **Detecting fork bombs** before they execute
5. **Blocking curl|bash and wget|sh** patterns that pipe untrusted code

## How It Works

When you ask me to execute a shell command, the plugin's PreToolUse hook intercepts it **before execution**. If the command matches a dangerous pattern, the hook:

- Returns `exit code 2` to block the operation
- Provides a helpful (and slightly snarky) explanation of why it was blocked
- Suggests safer alternatives when appropriate

## Protected Patterns

| Pattern | What It Blocks | Example Message |
|---------|----------------|-----------------|
| `rm -rf /...` | Recursive deletion of system directories | "Whoa there, friend! Trying to rm -rf a system directory is like playing Russian Roulette..." |
| `chmod 777 /...` | Overly permissive permissions on system paths | "chmod 777? Really? That's the security equivalent of leaving your front door open..." |
| `dd of=/dev/...` | Writing directly to block devices | "Attempting to dd directly to a device? Bold move! But I'm not about to let you..." |
| `:(){:|:&};:` | Fork bombs | "Nice try with the fork bomb! I appreciate the creativity, but..." |
| `curl ... \| bash` | Piping remote scripts to shell | "Piping unknown scripts directly to bash? That's like accepting candy from strangers..." |

## Safe Commands

All normal, safe commands work without interference:
- `ls`, `cd`, `mkdir`, `cat`, `grep`, etc.
- `rm` with specific files (not -rf on system dirs)
- Proper use of tools like `dd` with safe targets

## Example Interactions

**Dangerous (Blocked):**
```
User: Delete everything in /usr
Agent: *attempts rm -rf /usr*
Hook: 🛑 Blocks with explanation
```

**Safe (Allowed):**
```
User: List files in the current directory
Agent: *executes ls -la*
Hook: ✓ Allows execution
```

## Technical Details

- **Hook Type:** PreToolUse (runs before terminal tool execution)
- **Matcher:** `terminal` (only applies to terminal/shell commands)
- **Exit Codes:**
  - `0` = Allow command
  - `2` = Block command (with reason)
- **Timeout:** 5 seconds

This is a **blacklist** approach - it blocks known dangerous patterns while allowing everything else.
