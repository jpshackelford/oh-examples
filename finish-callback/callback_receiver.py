#!/usr/bin/env python3
"""A tiny stdlib-only web server that receives the finish callback.

Run this to prove the end-to-end flow: start it, expose it to the sandbox
(e.g. with a tunnel), point the plugin's ``OH_CALLBACK_URL`` at it, and watch
the POST arrive the moment the agent finishes.

    python callback_receiver.py                 # listen on 0.0.0.0:8000
    python callback_receiver.py --port 9000
    python callback_receiver.py --token s3cr3t  # require a shared-secret header

For each POST it prints a one-line summary plus the pretty-printed JSON body,
and replies ``204 No Content``. GET / returns a short liveness message so you
can eyeball it in a browser.

No third-party dependencies — just the Python standard library — so it runs
anywhere Python 3.8+ does.
"""

import argparse
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


# Set by main() from CLI args; read by the handler. A module-level holder keeps
# BaseHTTPRequestHandler's constructor signature untouched.
_EXPECTED_TOKEN: str | None = None


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")


class CallbackHandler(BaseHTTPRequestHandler):
    # Silence the default per-request stderr logging; we print our own lines.
    def log_message(self, *_args) -> None:
        pass

    def do_GET(self) -> None:
        body = (
            b"oh-finish-callback receiver is up. "
            b"POST your finish callbacks to this URL.\n"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0) or 0)
        raw = self.rfile.read(length) if length else b""

        # Optional shared-secret check. The plugin sends the same value in the
        # X-Callback-Token header when OH_CALLBACK_TOKEN is set.
        if _EXPECTED_TOKEN is not None:
            got = self.headers.get("X-Callback-Token")
            if got != _EXPECTED_TOKEN:
                print(f"[{_now()}] REJECTED {self.path} — bad/missing token")
                self.send_response(403)
                self.end_headers()
                return

        print(f"\n[{_now()}] POST {self.path}  ({length} bytes)")
        ctype = self.headers.get("Content-Type", "")
        if raw:
            try:
                parsed = json.loads(raw.decode("utf-8"))
                print(json.dumps(parsed, indent=2, sort_keys=True))
            except (ValueError, UnicodeDecodeError):
                print(f"  (non-JSON body, Content-Type: {ctype!r})")
                print(f"  {raw!r}")
        else:
            print("  (empty body)")
        sys.stdout.flush()

        self.send_response(204)
        self.end_headers()


def main() -> int:
    global _EXPECTED_TOKEN

    parser = argparse.ArgumentParser(
        description="Receive OpenHands finish callbacks and print them.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--host", default="0.0.0.0", help="Interface to bind.")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on.")
    parser.add_argument(
        "--token",
        default=None,
        help="If set, require this value in the X-Callback-Token header.",
    )
    args = parser.parse_args()

    _EXPECTED_TOKEN = args.token

    server = ThreadingHTTPServer((args.host, args.port), CallbackHandler)
    where = f"http://{args.host}:{args.port}"
    print(f"[{_now()}] Listening on {where}")
    if args.token:
        print("  Requiring X-Callback-Token header on POSTs.")
    print("  Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
