#!/usr/bin/env python3
"""Vitrine Infrastructure Network Guard V1.

Usage: python3 network/network_guard.py <compose.yml> [<compose.yml> ...]
Exit 0: approved. Exit 2: deployment blocked.
"""
from pathlib import Path
import re
import sys

SHARED_NETWORK = "n8n-traefik_app_network"


def scan(path: Path):
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    violations = []

    # V1 intentionally fails closed for static addresses in compose files that
    # reference the shared edge network. This prevents recurrence of the
    # 2026-09-17 collision class.
    if SHARED_NETWORK in text:
        for number, line in enumerate(lines, 1):
            if re.match(r"^\s*ipv4_address\s*:", line):
                violations.append(
                    f"{path}:{number}: ipv4_address prohibited when {SHARED_NETWORK} is referenced"
                )

    return violations


def main():
    if len(sys.argv) < 2:
        print("usage: network_guard.py <compose.yml> [<compose.yml> ...]", file=sys.stderr)
        return 2

    violations = []
    for raw in sys.argv[1:]:
        path = Path(raw)
        if not path.is_file():
            violations.append(f"{path}: compose file not found")
            continue
        violations.extend(scan(path))

    if violations:
        print("DEPLOY_BLOCKED")
        for violation in violations:
            print(f"- {violation}")
        return 2

    print("NETWORK_GUARD_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
