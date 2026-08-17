from __future__ import annotations

import argparse
import json
import socket
from pathlib import Path


def resolve_ipv4(hostname: str) -> list[str]:
    try:
        return sorted(
            {
                entry[4][0]
                for entry in socket.getaddrinfo(
                    hostname,
                    443,
                    family=socket.AF_INET,
                    type=socket.SOCK_STREAM,
                )
            }
        )
    except socket.gaierror:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Valida se rotas selecionadas resolvem para o VPS esperado antes da publicacao Nginx/SSL."
    )
    parser.add_argument("--expected-ip", required=True)
    parser.add_argument("--registry", default="routing/routes.json")
    parser.add_argument(
        "--route-id",
        action="append",
        dest="route_ids",
        help="Valida apenas esta rota. Pode ser repetido para validar varias rotas.",
    )
    args = parser.parse_args()

    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    requested = set(args.route_ids or [])
    known_ids = {route.get("id") for route in registry.get("routes", [])}
    unknown = sorted(requested - known_ids)
    if unknown:
        print(json.dumps({"ok": False, "error": "unknown_route_ids", "route_ids": unknown}, indent=2))
        return 3

    result: dict[str, object] = {
        "expected_ip": args.expected_ip,
        "route_ids": sorted(requested) if requested else "all_enabled",
        "hosts": {},
    }

    ok = True
    checked = 0
    for route in registry.get("routes", []):
        if route.get("status") == "disabled":
            continue
        if requested and route.get("id") not in requested:
            continue

        hostname = route["hostname"]
        ipv4 = resolve_ipv4(hostname)
        points_to_expected_ip = args.expected_ip in ipv4
        checked += 1

        result["hosts"][hostname] = {
            "route_id": route.get("id"),
            "ipv4": ipv4,
            "points_to_expected_ip": points_to_expected_ip,
        }
        ok = ok and points_to_expected_ip

    if checked == 0:
        ok = False

    result["checked"] = checked
    result["ok"] = ok
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
