# Agent Canvas UI Extensions (Experimental)

> ⚠️ **EXPERIMENTAL** — The examples in this directory showcase experimental UI extension
> functionality from [OpenHands/agent-canvas](https://github.com/OpenHands/agent-canvas).
> This feature is under active development and **may never be released** as a stable API.
> The extension system, manifest format, and host APIs are subject to breaking changes
> without notice.

## What are UI Extensions?

UI extensions are small, sandboxed bundles that add custom UI to Agent Canvas (sidebar
panels, commands, menus) without modifying the host application. They run isolated from
your DOM, cookies, and credentials — every capability must be explicitly approved at
install time.

## Requirements

To use these examples, you need:

1. A build of Agent Canvas from the `feature/ui-extensions` branch
2. The `VITE_ENABLE_EXTENSIONS=true` build flag enabled
3. Access to the `/extensions` page in the Agent Canvas UI

## Examples

| Extension | Description |
|-----------|-------------|
| [dad-jokes](./dad-jokes/) | 👴 Because every coding session needs more groaning — sidebar panel, commands, menus, and settings |

## Reference

For the authoritative documentation on the extension system, see the `feature/ui-extensions`
branch of [OpenHands/agent-canvas](https://github.com/OpenHands/agent-canvas):

- `docs/EXTENSIONS.md` — User guide for installing and managing extensions
- `docs/EXTENSION_POINTS.md` — Reference for all contribution points
- `src/extensions/README.md` — Internal architecture and module reference
- `docs/proposals/ui-extensions.md` — Design proposal and rationale

## Disclaimer

These examples are provided for experimentation and feedback purposes only. Do not build
production workflows that depend on this functionality until it reaches a stable release.
