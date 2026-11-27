"""Pair with an IKEA DIRIGERA hub and print an access token.

    python -m home_assistant.builtin_plugins.smart_home.pair_dirigera 192.168.1.50

You'll be asked to press the action button on the bottom of the hub.
"""

from __future__ import annotations

import secrets
import sys

import requests
import urllib3

try:
    from dirigera.hub.auth import ALPHABET, get_token, send_challenge
except ImportError:
    sys.exit("The `dirigera` package is missing: pip install dirigera")

# The hub uses a self-signed certificate, so HTTPS verification is off for it.
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


def main() -> None:
    host = sys.argv[1] if len(sys.argv) > 1 else input("DIRIGERA hub IP address: ").strip()
    if not host:
        sys.exit("No IP address given. Find the hub in your router's list of connected devices.")

    # PKCE code verifier; generated with `secrets` (the library's helper uses `random`).
    verifier = "".join(secrets.choice(ALPHABET) for _ in range(128))
    try:
        code = send_challenge(host, verifier)
    except requests.RequestException as e:
        sys.exit(f"Couldn't reach a DIRIGERA hub at {host}:8443 ({e}).\nCheck the IP and that you're on the same network.")

    input("Now press the action button on the bottom of the hub, then press Enter here (within about a minute)... ")
    try:
        token = get_token(host, code, verifier)
    except requests.RequestException as e:
        sys.exit(f"Pairing failed ({e}). Run this again and press the hub's button before pressing Enter.")

    try:
        from dirigera import Hub
        count = len(Hub(token=token, ip_address=host).get("/devices"))
        print(f"\nPaired. The hub reports {count} devices.")
    except Exception as e:
        print(f"\nGot a token, but listing devices failed ({e}).")

    print("\nAdd these to your shell (e.g. ~/.bashrc). Keep the token private, since it controls your home:\n")
    print(f'export DIRIGERA_HOST="{host}"')
    print(f'export DIRIGERA_TOKEN="{token}"')
    print('export HA_BACKEND="dirigera"')


if __name__ == "__main__":
    main()
