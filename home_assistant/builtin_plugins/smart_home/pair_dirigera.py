"""Pair with an IKEA DIRIGERA hub and save the access token.

    python -m home_assistant.builtin_plugins.smart_home.pair_dirigera 192.168.1.50

Starts pairing, then waits (up to --timeout seconds) for you to press the action
button on the bottom of the hub. The token is saved to the project's .env file
(git-ignored, readable only by you), which the app loads automatically. Use
--print to show the token instead.
"""

from __future__ import annotations

import argparse
import os
import secrets
import sys
import time
from pathlib import Path

import requests
import urllib3

try:
    from dirigera.hub.auth import ALPHABET, get_token, send_challenge
except ImportError:
    sys.exit("The `dirigera` package is missing: pip install dirigera")

from home_assistant.config import ENV_FILE

# The hub uses a self-signed certificate, so HTTPS verification is off for it.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def save_env(path: Path, values: dict[str, str]) -> None:
    """Set keys in a .env file, keeping any other lines, with owner-only permissions."""
    lines = path.read_text().splitlines() if path.exists() else []
    kept = [l for l in lines if l.split("=", 1)[0].removeprefix("export ").strip() not in values]
    kept += [f'{k}="{v}"' for k, v in values.items()]
    path.write_text("\n".join(kept) + "\n")
    os.chmod(path, 0o600)


def main() -> None:
    p = argparse.ArgumentParser(description="Pair with an IKEA DIRIGERA hub")
    p.add_argument("host", help="the hub's IP address")
    p.add_argument("--timeout", type=int, default=120, help="seconds to wait for the button press (default 120)")
    p.add_argument("--print", action="store_true", help="print the token instead of saving it to .env")
    args = p.parse_args()

    # PKCE code verifier; generated with `secrets` (the library's helper uses `random`).
    verifier = "".join(secrets.choice(ALPHABET) for _ in range(128))
    try:
        code = send_challenge(args.host, verifier)
    except requests.RequestException as e:
        sys.exit(f"Couldn't reach a DIRIGERA hub at {args.host}:8443 ({e}).")

    print(f"Pairing started. Press the action button on the bottom of the hub now "
          f"(waiting up to {args.timeout} s)...", flush=True)
    deadline, last_error, token = time.monotonic() + args.timeout, None, None
    while time.monotonic() < deadline:
        try:
            token = get_token(args.host, code, verifier)
            break
        except requests.HTTPError as e:  # not pressed yet
            last_error = f"{e.response.status_code} {e.response.text[:120]}" if e.response is not None else str(e)
        except requests.RequestException as e:
            last_error = str(e)
        time.sleep(1.5)
    if not token:
        sys.exit(f"Timed out waiting for the button press (last hub response: {last_error}). Run this again.")

    try:
        from dirigera import Hub
        count = len(Hub(token=token, ip_address=args.host).get("/devices"))
        print(f"Paired. The hub reports {count} devices.")
    except Exception as e:
        print(f"Got a token, but listing devices failed ({e}).")

    values = {"DIRIGERA_HOST": args.host, "DIRIGERA_TOKEN": token, "HA_BACKEND": "dirigera"}
    if args.print:
        print("\n" + "\n".join(f'export {k}="{v}"' for k, v in values.items()))
    else:
        save_env(ENV_FILE, values)
        print(f"Saved DIRIGERA_HOST, DIRIGERA_TOKEN and HA_BACKEND=dirigera to {ENV_FILE} (owner-only, git-ignored).")


if __name__ == "__main__":
    main()
