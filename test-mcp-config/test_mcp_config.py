#!/usr/bin/env python3
"""Validate MCP server configs against a real sandbox's agent-server.

The OpenHands web UI lets you *add* an MCP server but does not (yet) tell you
whether it actually connects: a bad URL / token / network path simply means the
server's tools never show up in a conversation, with no error in the UI. This
script closes that gap from the API side.

Flow (mirrors ``start-sandbox``):

    1. POST /api/v1/sandboxes               -> start a sandbox (no conversation)
    2. GET  /api/v1/sandboxes?id=<id>       -> poll until status == RUNNING
    3. read exposed_urls[AGENT_SERVER].url  -> the sandbox's agent-server
       and session_api_key
    4. POST {agent_server}/api/mcp/test     -> validate each server config

``POST /api/mcp/test`` connects to one candidate MCP server, lists its tools,
and (optionally) invokes one read-only tool to exercise credentials. It returns
HTTP 200 in both the success and failure cases -- a failed connection is the
*expected* outcome when validating user input, not a server error:

    {"ok": true,  "tools": [...], "tool_result": {...}|null}
    {"ok": false, "error": "...", "error_kind": "timeout"|"connection"|"unknown"}

Examples
--------
    export OH_API_KEY=...

    # Test a single remote (streamable-http) server with a bearer token:
    python test_mcp_config.py \
        --url https://mcp.example.com/mcp --type shttp --server-api-key "$TOKEN"

    # Add a header instead of a bearer token, and exercise credentials by
    # invoking a known read-only tool:
    python test_mcp_config.py --url https://mcp.example.com/mcp \
        --header "Authorization=Bearer $TOKEN" \
        --tool-call list_things

    # Test a stdio (subprocess) server:
    python test_mcp_config.py --command npx --arg -y --arg some-mcp-server

    # Test every server in an SDK-style config file
    # ({"mcpServers": {"<name>": {"url": ..., "transport": "http"}, ...}}):
    python test_mcp_config.py --config my_mcp_config.json

    # Test the servers actually saved in your account settings:
    python test_mcp_config.py --from-settings

    # See which servers are configured (no sandbox started), then test one:
    python test_mcp_config.py --from-settings --list
    python test_mcp_config.py --from-settings --server jira --server figma

    # Reuse a sandbox you already started (skips create + delete):
    python test_mcp_config.py --sandbox-id <id> --url https://mcp.example.com/mcp

Env vars: OH_API_KEY, OH_API_BASE, SANDBOX_SPEC_ID, POLL_TIMEOUT.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

import requests


# --------------------------------------------------------------------------- #
# Sandbox lifecycle (same shape as start-sandbox/sandbox_demo.py)
# --------------------------------------------------------------------------- #
def start_sandbox(base_url: str, headers: dict, spec_id: str | None) -> dict:
    """POST /api/v1/sandboxes -> SandboxInfo (status is initially STARTING)."""
    params = {"sandbox_spec_id": spec_id} if spec_id else None
    resp = requests.post(f"{base_url}/api/v1/sandboxes", headers=headers, params=params)
    resp.raise_for_status()
    return resp.json()


def get_sandbox(base_url: str, headers: dict, sandbox_id: str) -> dict:
    resp = requests.get(
        f"{base_url}/api/v1/sandboxes", headers=headers, params={"id": sandbox_id}
    )
    resp.raise_for_status()
    results = resp.json()
    if not results or results[0] is None:
        raise ValueError(f"Sandbox {sandbox_id} not found")
    return results[0]


def wait_until_running(
    base_url: str, headers: dict, sandbox_id: str, timeout: int
) -> dict:
    """Poll the batch-get-by-id endpoint until status == RUNNING."""
    deadline = time.monotonic() + timeout
    while True:
        sb = get_sandbox(base_url, headers, sandbox_id)
        print("  status:", sb["status"])
        if sb["status"] == "RUNNING":
            return sb
        if time.monotonic() > deadline:
            raise TimeoutError(
                f"Sandbox {sandbox_id} did not reach RUNNING within {timeout}s "
                f"(last status: {sb['status']})"
            )
        time.sleep(3)


def agent_server_url(sandbox: dict) -> str:
    """Pick the AGENT_SERVER entry from the sandbox's exposed_urls."""
    url = next(
        (u["url"] for u in sandbox["exposed_urls"] if u["name"] == "AGENT_SERVER"),
        None,
    )
    if not url:
        raise ValueError(f"AGENT_SERVER URL not found in sandbox {sandbox['id']}")
    return url


def delete_sandbox(base_url: str, headers: dict, sandbox_id: str) -> None:
    requests.delete(
        f"{base_url}/api/v1/sandboxes/{sandbox_id}",
        headers=headers,
        params={"sandbox_id": sandbox_id},
    )


# --------------------------------------------------------------------------- #
# Building MCP test requests
# --------------------------------------------------------------------------- #
def _kv_pairs(values: list[str] | None) -> dict[str, str]:
    """Parse repeated ``key=value`` flags into a dict."""
    out: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise ValueError(f"expected key=value, got {item!r}")
        key, value = item.split("=", 1)
        out[key] = value
    return out


def server_specs_from_args(
    args: argparse.Namespace, base_url: str, app_headers: dict
) -> list[tuple[str, dict]]:
    """Return a list of (name, server_spec) to test.

    A ``server_spec`` matches the ``server`` field of ``POST /api/mcp/test``:
    a remote spec ({type, url, headers, api_key}) or a stdio spec
    ({type, command, args, env, cwd}).
    """
    if args.from_settings:
        servers = fetch_settings_servers(base_url, app_headers, args.settings_url)
        specs = [(name, _to_server_spec(cfg)) for name, cfg in servers.items()]
        return _filter_by_name(specs, args.server)

    if args.config:
        return _filter_by_name(_specs_from_config_file(args.config), args.server)

    if args.command:
        spec: dict = {
            "type": "stdio",
            "command": args.command,
            "args": list(args.arg or []),
        }
        env = _kv_pairs(args.env)
        if env:
            spec["env"] = env
        return [(args.name, spec)]

    if args.url:
        spec = {"type": args.type, "url": args.url}
        headers = _kv_pairs(args.header)
        if headers:
            spec["headers"] = headers
        if args.server_api_key:
            spec["api_key"] = args.server_api_key
        return [(args.name, spec)]

    raise SystemExit(
        "error: provide one of --from-settings, --url, --command, or --config "
        "(see --help for examples)"
    )


def _filter_by_name(
    specs: list[tuple[str, dict]], wanted: list[str] | None
) -> list[tuple[str, dict]]:
    """Keep only servers named in ``wanted`` (no filter -> keep all)."""
    if not wanted:
        return specs
    by_name = dict(specs)
    missing = [n for n in wanted if n not in by_name]
    if missing:
        raise SystemExit(
            f"error: server(s) not found: {', '.join(missing)}. "
            f"Available: {', '.join(by_name) or '(none)'}"
        )
    return [(n, by_name[n]) for n in wanted]


def _to_server_spec(cfg: dict) -> dict:
    """Map one stored/SDK server entry to a ``/api/mcp/test`` server spec.

    Handles both stdio ({command, args, env, cwd}) and remote servers, and the
    several spellings the settings layer uses for a remote bearer token
    (``api_key`` or ``auth``) and transport (``transport`` or ``type``).
    """
    if "command" in cfg:
        spec: dict = {"type": "stdio", "command": cfg["command"]}
        for key in ("args", "env", "cwd"):
            if cfg.get(key):
                spec[key] = cfg[key]
        return spec

    spec = {
        "type": cfg.get("transport") or cfg.get("type") or "shttp",
        "url": cfg["url"],
    }
    if cfg.get("headers"):
        spec["headers"] = cfg["headers"]
    token = cfg.get("api_key") or cfg.get("auth")
    if token:
        spec["api_key"] = token
    return spec


def _specs_from_config_file(path: str) -> list[tuple[str, dict]]:
    """Map an SDK-style {"mcpServers": {...}} config to per-server test specs."""
    with open(path) as fh:
        data = json.load(fh)
    servers = data.get("mcpServers", data)
    if not isinstance(servers, dict) or not servers:
        raise SystemExit(f"error: no servers found in {path}")
    return [(name, _to_server_spec(cfg)) for name, cfg in servers.items()]


def fetch_settings_servers(
    base_url: str, app_headers: dict, settings_url: str | None
) -> dict:
    """GET the caller's settings and return agent_settings.mcp_config.mcpServers."""
    url = settings_url or f"{base_url}/api/v1/settings"
    resp = requests.get(url, headers=app_headers)
    resp.raise_for_status()
    mcp_config = (resp.json().get("agent_settings") or {}).get("mcp_config") or {}
    servers = mcp_config.get("mcpServers", {})
    if not servers:
        raise SystemExit(
            f"error: no MCP servers configured in settings ({url}). "
            "Add one in the MCP settings UI first."
        )
    return servers


def _redacted_target(spec: dict) -> str:
    """A printable target string that never includes secrets."""
    if spec.get("type") == "stdio":
        return " ".join([spec["command"], *spec.get("args", [])])
    return spec.get("url", "?")


def test_one_server(
    agent_url: str,
    session: dict,
    name: str,
    server_spec: dict,
    timeout: float,
    tool_call: dict | None,
) -> dict:
    """POST /api/mcp/test for a single server and return the parsed body."""
    payload: dict = {"name": name, "server": server_spec, "timeout": timeout}
    if tool_call:
        payload["tool_call"] = tool_call
    resp = requests.post(
        f"{agent_url}/api/mcp/test",
        headers=session,
        json=payload,
        timeout=timeout + 30,
    )
    if resp.status_code == 404:
        raise SystemExit(
            "error: POST /api/mcp/test returned 404 -- this sandbox's "
            "agent-server is too old (the endpoint was added in agent-server "
            "1.29.0 / OpenHands 1.8.0). Upgrade the runtime image to use it."
        )
    resp.raise_for_status()
    return resp.json()


def print_result(name: str, server_spec: dict, result: dict) -> bool:
    """Pretty-print one result. Returns True if the server is OK."""
    label = f"{server_spec.get('type')}: {_redacted_target(server_spec)}"
    print(f"\n--- {name}  ({label}) ---")
    if result.get("ok"):
        tools = result.get("tools", [])
        shown = ", ".join(tools[:12])
        if len(tools) > 12:
            shown += f", ... (+{len(tools) - 12} more)"
        print(f"  OK  connected; {len(tools)} tool(s): {shown or '(none)'}")
        tr = result.get("tool_result")
        if tr is not None:
            flag = "ERROR" if tr.get("is_error") else "ok"
            print(f"  tool_call -> {flag}: {tr.get('text', '')[:300]}")
        return True
    print(f"  FAIL  [{result.get('error_kind')}] {result.get('error')}")
    return False


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--api-key", default=os.environ.get("OH_API_KEY"))
    p.add_argument(
        "--base-url",
        default=os.environ.get("OH_API_BASE", "https://app.all-hands.dev"),
    )
    p.add_argument("--sandbox-spec-id", default=os.environ.get("SANDBOX_SPEC_ID"))
    p.add_argument(
        "--sandbox-id",
        help="Reuse an existing RUNNING sandbox instead of creating one.",
    )
    p.add_argument(
        "--poll-timeout",
        type=int,
        default=int(os.environ.get("POLL_TIMEOUT", "180")),
    )
    p.add_argument(
        "--keep",
        action="store_true",
        help="Leave the sandbox running (always on when --sandbox-id is given).",
    )

    # What to test --------------------------------------------------------- #
    p.add_argument("--name", default="test-server", help="Logical server name.")
    p.add_argument("--url", help="Remote server URL (http/sse).")
    p.add_argument(
        "--type",
        default="shttp",
        choices=["http", "shttp", "streamable-http", "sse"],
        help="Remote transport type (default: shttp).",
    )
    p.add_argument("--server-api-key", help="Bearer token sent as Authorization.")
    p.add_argument(
        "--header",
        action="append",
        help="Extra header key=value (repeatable).",
    )
    p.add_argument("--command", help="Stdio server executable.")
    p.add_argument("--arg", action="append", help="Stdio arg (repeatable).")
    p.add_argument("--env", action="append", help="Stdio env key=value (repeatable).")
    p.add_argument(
        "--config",
        help='SDK-style config file: {"mcpServers": {"name": {...}}}.',
    )
    p.add_argument(
        "--from-settings",
        action="store_true",
        help="Test the servers in your stored agent_settings.mcp_config.",
    )
    p.add_argument(
        "--settings-url",
        help="Override the settings URL (default: {base-url}/api/v1/settings).",
    )
    p.add_argument(
        "--server",
        action="append",
        help="Only test this server name (repeatable). Default: test all.",
    )
    p.add_argument(
        "--list",
        action="store_true",
        help="List the selected servers and exit (no sandbox is started).",
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=15.0,
        help="Per-server connect timeout in seconds (default: 15).",
    )
    p.add_argument(
        "--tool-call",
        help="Optional read-only tool to invoke after listing (credential check).",
    )
    p.add_argument(
        "--tool-arg",
        action="append",
        help="Argument key=value for --tool-call (repeatable).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if not args.api_key:
        sys.exit("error: set --api-key or the OH_API_KEY environment variable")

    app_headers = {"X-Session-API-Key": args.api_key}
    specs = server_specs_from_args(args, args.base_url, app_headers)

    if args.list:
        print(f"{len(specs)} server(s):")
        for name, spec in specs:
            print(f"  - {name}  ({spec.get('type')}: {_redacted_target(spec)})")
        sys.exit(0)

    tool_call = None
    if args.tool_call:
        tool_call = {"name": args.tool_call, "arguments": _kv_pairs(args.tool_arg)}

    created = False
    sandbox_id = args.sandbox_id
    failures = 0
    try:
        if sandbox_id:
            sb = get_sandbox(args.base_url, app_headers, sandbox_id)
            if sb["status"] != "RUNNING":
                sb = wait_until_running(
                    args.base_url, app_headers, sandbox_id, args.poll_timeout
                )
        else:
            sb = start_sandbox(args.base_url, app_headers, args.sandbox_spec_id)
            sandbox_id = sb["id"]
            created = True
            print("sandbox:", sandbox_id)
            sb = wait_until_running(
                args.base_url, app_headers, sandbox_id, args.poll_timeout
            )

        agent_url = agent_server_url(sb)
        session = {"X-Session-API-Key": sb["session_api_key"]}
        print("agent:", agent_url)

        for name, spec in specs:
            result = test_one_server(
                agent_url, session, name, spec, args.timeout, tool_call
            )
            if not print_result(name, spec, result):
                failures += 1

        print(f"\n{len(specs) - failures}/{len(specs)} server(s) OK.")
    finally:
        if created and not args.keep and sandbox_id:
            print(f"\nDeleting sandbox {sandbox_id} ...")
            delete_sandbox(args.base_url, app_headers, sandbox_id)
        elif sandbox_id:
            print(f"\nSandbox {sandbox_id} left running.")

    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
