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
        description="Valida se as rotas HML resolvem para o VPS esperado antes da publicacao Nginx/SSL."
    )
    parser.add_argument("--expected-ip", required=True)
    parser.add_argument("--registry", default="routing/routes.json")
    args = parser.parse_args()

    registry = json.loads(Path(args.registry).read_text(encoding="utf-8"))
    result: dict[str, object] = {
        "expected_ip": args.expected_ip,
        "hosts": {},
    }

    ok = True
    for route in registry.get("routes", []):
        if route.get("status") == "disabled":
            continue

        hostname = route["hostname"]
        ipv4 = resolve_ipv4(hostname)
        points_to_expected_ip = args.expected_ip in ipv4

        result["hosts"][hostname] = {
            "ipv4": ipv4,
            "points_to_expected_ip": points_to_expected_ip,
        }

        if hostname == "hml.vitrineiapro.com.br" or hostname.endswith(".hml.vitrineiapro.com.br"):
            ok = ok and points_to_expected_ip

    result["ok"] = ok
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
