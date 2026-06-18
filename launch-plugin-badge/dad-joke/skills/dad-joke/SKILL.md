---
description: Ask for the user's favorite animal, then tell a dad joke about it
triggers:
  - dad joke
  - tell me a joke
  - make me laugh
---

# Dad Joke Skill

Activated when the user asks for a dad joke.

## Instructions

1. If the user has not already named an animal, ask: **"What's your favorite
   animal?"** and wait for their reply.
2. Once you know the animal, tell exactly one short, family-friendly dad joke
   (a pun is ideal) about it — setup and punchline only, no preamble.

## Purpose

A skill (as opposed to the `/dad-joke:about` command) lets the examples show the
"load the plugin, then let the user prompt" flow: the agent does nothing on
launch, but as soon as the user asks for a joke it asks for their favorite
animal and delivers.
