# Entry Point

Demo script that showcases the full flow and attempts to extract secrets.

## Purpose

This script:
1. Starts an OpenHands conversation with the `launch-plugin`
2. Simulates a customer interaction requesting a travel guide
3. Demonstrates that the proprietary prompts remain hidden
4. Attempts various techniques to extract secrets (and fails)

## Usage

```bash
uv run python demo.py
```

## What to Observe

- The travel guide gets generated with "mysteriously specific" restaurant recommendations
- Attempts to interrogate the agent about its prompts yield nothing useful
- The `uncle_mortimers_secrets.json` content never appears in the public conversation
