#!/usr/bin/env python3
"""Tiny stdlib-only webhook receiver for agent-server outbound webhooks.

The OpenHands agent-server (when configured with a ``WebhookSpec``) POSTs to
two URLs derived from the spec's ``base_url``:

    POST {base_url}/conversations         -> a full ConversationInfo, fired on
                                             conversation START / PAUSE / RESUME
                                             / STOP. This is the "state changed"
                                             signal.
    POST {base_url}/events/{conv_id_hex}  -> a JSON array of batched Event
                                             objects.

This server prints one concise line per callback and nothing else. It has no
third-party dependencies so it can run anywhere Python 3.10+ is available.

Usage:

    python receiver.py                 # listen on 0.0.0.0:8080
    python receiver.py --port 9000     # custom port
    python receiver.py --host 127.0.0.1

Env vars: RECEIVER_HOST, RECEIVER_PORT.
"""

import argparse
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class WebhookHandler(BaseHTTPRequestHandler):
    """Handle the two webhook paths the agent-server posts to."""

    def _read_json(self) -> object:
        """Read and JSON-decode the request body (returns None on failure)."""
        length = int(self.headers.get("Content-Length", 0))
        raw = self.rfile.read(length) if length else b""
        try:
            return json.loads(raw) if raw else None
        except json.JSONDecodeError:
            return None

    def _respond(self, code: int = 200) -> None:
        """Send a minimal JSON acknowledgement so the server sees 2xx."""
        body = b'{"ok": true}'
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        path = self.path.rstrip("/")
        payload = self._read_json()

        if path.endswith("/conversations"):
            self._print_conversation(payload)
        elif "/events/" in path:
            conv_hex = path.rsplit("/events/", 1)[-1]
            self._print_events(conv_hex, payload)
        else:
            print(f"[receiver] POST {self.path} (unhandled)", flush=True)

        self._respond()

    def _print_conversation(self, info: object) -> None:
        """Print the conversation id + execution status from a ConversationInfo."""
        if not isinstance(info, dict):
            print("[conversations] <non-object payload>", flush=True)
            return
        conv_id = info.get("id", "?")
        status = info.get("execution_status", "?")
        title = info.get("title")
        suffix = f" title={title!r}" if title else ""
        print(
            f"[conversations] id={conv_id} execution_status={status}{suffix}",
            flush=True,
        )

    def _print_events(self, conv_hex: str, events: object) -> None:
        """Print each event's ``kind`` from a batched /events payload."""
        if not isinstance(events, list):
            print(f"[events/{conv_hex}] <non-array payload>", flush=True)
            return
        kinds = [e.get("kind", "?") if isinstance(e, dict) else "?" for e in events]
        print(
            f"[events/{conv_hex}] {len(kinds)} event(s): {', '.join(kinds)}",
            flush=True,
        )

    def log_message(self, format: str, *args: object) -> None:  # noqa: A002, ARG002
        """Silence the default per-request stderr logging."""
        return


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--host",
        default=os.environ.get("RECEIVER_HOST", "0.0.0.0"),
        help="Interface to bind (default: $RECEIVER_HOST or 0.0.0.0).",
    )
    p.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("RECEIVER_PORT", "8080")),
        help="Port to bind (default: $RECEIVER_PORT or 8080).",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    server = ThreadingHTTPServer((args.host, args.port), WebhookHandler)
    print(
        f"[receiver] listening on http://{args.host}:{args.port} "
        "(POST /conversations, POST /events/{id})",
        flush=True,
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[receiver] shutting down", flush=True)
        server.shutdown()
        sys.exit(0)


if __name__ == "__main__":
    main()
