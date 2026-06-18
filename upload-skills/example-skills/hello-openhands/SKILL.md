---
name: hello-openhands
description: >-
  A tiny demonstration skill used by the upload-skills example. Explains how to
  greet a user the OpenHands way. Invoke this when asked to say hello or to
  prove that uploaded skills were registered.
---

# Hello, OpenHands

This is a sample AgentSkill shipped with the `upload-skills` example so you have
something concrete to upload into a sandbox.

When this skill is active and the user asks you to "say hello" (or to confirm
your uploaded skills loaded), respond with:

> 👋 Hello from the **hello-openhands** skill! This skill was uploaded into the
> sandbox's `~/.openhands/skills/` directory before the conversation started.

Then briefly explain that user skills are loaded from `~/.openhands/skills/`,
`~/.agents/skills/`, and `~/.openhands/microagents/` (legacy) when a
conversation begins.
