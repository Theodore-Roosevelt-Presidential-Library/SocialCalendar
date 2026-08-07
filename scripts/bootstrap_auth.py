#!/usr/bin/env python3
"""
One-time, run-it-on-your-laptop OAuth bootstrap for the Hootsuite calendar.

Hootsuite has no machine-to-machine grant for the publishing API, so a human has
to authorize the app once. This script does that, then prints the three values
that go into GitHub repository secrets.

    pip install -r scripts/requirements.txt
    python scripts/bootstrap_auth.py

You will need, from https://hootsuite.com/developers/my-apps:
  * the app's Client ID and Client Secret
  * a redirect URI of exactly  http://localhost:8723/callback
    registered under  App directory -> Developer apps -> [app] -> Security -> Rest API

Run this again any time the refresh chain breaks (the workflow will tell you).
"""

from __future__ import annotations

import getpass
import http.server
import secrets
import socket
import sys
import threading
import urllib.parse
import webbrowser

from hootsuite import AUTH_URL, exchange_authorization_code

REDIRECT_PORT = 8723
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}/callback"

_result: dict[str, str] = {}
_done = threading.Event()

_PAGE = """<!doctype html><meta charset="utf-8">
<title>Hootsuite authorization</title>
<style>
  body{{font:16px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       display:grid;place-items:center;height:100vh;margin:0;background:#12100e;color:#f4efe6}}
  div{{max-width:32rem;padding:2rem;text-align:center}}
  h1{{font-size:1.4rem;margin:0 0 .5rem}}
  p{{margin:0;color:#b9ada0}}
</style>
<div><h1>{title}</h1><p>{body}</p></div>
"""


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != "/callback":
            self.send_error(404)
            return

        params = urllib.parse.parse_qs(parsed.query)
        if "error" in params:
            _result["error"] = params["error"][0]
            page = _PAGE.format(
                title="Authorization denied",
                body="You can close this tab and re-run the script.",
            )
        else:
            _result["code"] = params.get("code", [""])[0]
            _result["state"] = params.get("state", [""])[0]
            page = _PAGE.format(
                title="Authorized",
                body="Hootsuite is connected. You can close this tab and return "
                "to your terminal.",
            )

        body = page.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _done.set()

    def log_message(self, *_args):  # silence the default stderr logging
        pass


def main() -> int:
    print(__doc__)

    client_id = input("Hootsuite Client ID: ").strip()
    client_secret = getpass.getpass("Hootsuite Client Secret (hidden): ").strip()
    if not client_id or not client_secret:
        print("Both values are required.", file=sys.stderr)
        return 1

    try:
        server = http.server.HTTPServer(("localhost", REDIRECT_PORT), _Handler)
    except OSError as exc:
        print(
            f"Could not listen on {REDIRECT_URI} ({exc}). "
            f"Close whatever is using port {REDIRECT_PORT} and try again.",
            file=sys.stderr,
        )
        return 1

    state = secrets.token_urlsafe(24)  # Hootsuite requires >= 8 chars
    authorize = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": REDIRECT_URI,
            "scope": "offline",  # 'offline' is what makes a refresh token appear
            "state": state,
        }
    )

    threading.Thread(target=server.serve_forever, daemon=True).start()

    print("\nOpening your browser to authorize the app. If nothing happens, "
          "paste this URL yourself:\n")
    print(authorize + "\n")
    try:
        webbrowser.open(authorize)
    except Exception:
        pass

    if not _done.wait(timeout=300):
        print("Timed out waiting for the browser redirect.", file=sys.stderr)
        return 1
    server.shutdown()

    if "error" in _result:
        print(f"Authorization denied: {_result['error']}", file=sys.stderr)
        return 1
    if _result.get("state") != state:
        print("State mismatch - aborting. Try again.", file=sys.stderr)
        return 1

    tokens = exchange_authorization_code(
        client_id, client_secret, _result["code"], REDIRECT_URI
    )

    print("\n" + "=" * 68)
    print("Done. Add these as GitHub repository secrets:")
    print("  Settings -> Secrets and variables -> Actions -> New repository secret")
    print("=" * 68)
    print(f"\nHOOTSUITE_CLIENT_ID\n  {client_id}")
    print(f"\nHOOTSUITE_CLIENT_SECRET\n  {client_secret}")
    print(f"\nHOOTSUITE_REFRESH_TOKEN\n  {tokens.refresh_token}")
    print(
        "\nThe refresh token above is single-use. The workflow consumes it on the "
        "first run and writes its replacement back into the secret automatically, "
        "so do not run this script again unless the workflow tells you to."
    )
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        sys.exit(130)
