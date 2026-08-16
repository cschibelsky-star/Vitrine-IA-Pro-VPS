#!/usr/bin/env python3
import argparse
import json
import re
import sys
from pathlib import Path

HOST_RE = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
UPSTREAM_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*:([0-9]{1,5})$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")
ALLOWED_ENVIRONMENTS = {"homologation", "customer_provisional"}
ALLOWED_STATUSES = {"active", "pending_dns_proxy", "pending_app", "disabled"}


def _error(errors, message):
    errors.append(message)


def validate_registry(data):
    errors = []
    warnings = []
    if data.get("schema_version") != "1.0":
        _error(errors, "schema_version deve ser 1.0")
    if data.get("network") != "vitrine_net":
        _error(errors, "network deve ser vitrine_net")

    bases = data.get("base_domains") or {}
    hml_base = bases.get("homologation")
    client_base = bases.get("customer_provisional")
    if hml_base != "hml.vitrineiapro.com.br":
        _error(errors, "base_domains.homologation invalido")
    if client_base != "cliente.vitrineiapro.com.br":
        _error(errors, "base_domains.customer_provisional invalido")

    seen_ids = set()
    seen_hosts = set()
    routes = data.get("routes")
    if not isinstance(routes, list):
        _error(errors, "routes deve ser uma lista")
        routes = []

    for idx, route in enumerate(routes):
        prefix = f"routes[{idx}]"
        if not isinstance(route, dict):
            _error(errors, f"{prefix} deve ser objeto")
            continue

        route_id = route.get("id", "")
        if not ID_RE.fullmatch(route_id):
            _error(errors, f"{prefix}.id invalido: {route_id!r}")
        elif route_id in seen_ids:
            _error(errors, f"id duplicado: {route_id}")
        else:
            seen_ids.add(route_id)

        env = route.get("environment")
        if env not in ALLOWED_ENVIRONMENTS:
            _error(errors, f"{prefix}.environment invalido: {env!r}")

        hostname = route.get("hostname", "")
        if not HOST_RE.fullmatch(hostname):
            _error(errors, f"{prefix}.hostname invalido: {hostname!r}")
        else:
            if env == "homologation" and hostname != hml_base and not hostname.endswith("." + hml_base):
                _error(errors, f"hostname HML fora do dominio oficial: {hostname}")
            if env == "customer_provisional" and not hostname.endswith("." + client_base):
                _error(errors, f"hostname provisoria fora do dominio oficial: {hostname}")
            if hostname in seen_hosts:
                _error(errors, f"hostname/alias duplicado: {hostname}")
            seen_hosts.add(hostname)

        aliases = route.get("legacy_aliases", [])
        if not isinstance(aliases, list):
            _error(errors, f"{prefix}.legacy_aliases deve ser lista")
            aliases = []
        for alias in aliases:
            if not isinstance(alias, str) or not HOST_RE.fullmatch(alias):
                _error(errors, f"alias invalido em {prefix}: {alias!r}")
                continue
            if not alias.endswith(".vitrineiapro.com.br"):
                _error(errors, f"alias fora de vitrineaipro.com.br: {alias}")
            if alias in seen_hosts:
                _error(errors, f"hostname/alias duplicado: {alias}")
            seen_hosts.add(alias)

        upstream = route.get("upstream", "")
        match = UPSTREAM_RE.fullmatch(upstream)
        if not match:
            _error(errors, f"{prefix}.upstream invalido: {upstream!r}")
        else:
            port = int(match.group(1))
            if not 1 <= port <= 65535:
                _error(errors, f"porta upstream invalida em {prefix}: {port}")

        health = route.get("health_path", "")
        if not isinstance(health, str) or not health.startswith("/") or any(c in health for c in "\r\n"):
            _error(errors, f"{prefix}.health_path invalido")

        if route.get("ssl") is not True:
            _error(errors, f"{prefix}.ssl deve ser true")

        status = route.get("status")
        if status not in ALLOWED_STATUSES:
            _error(errors, f"{prefix}.status invalido: {status!r}")
        if status == "disabled":
            warnings.append(f"rota desabilitada: {route_id}")

    return errors, warnings


def load_and_validate(path):
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    errors, warnings = validate_registry(data)
    return data, errors, warnings


def main():
    parser = argparse.ArgumentParser(description="Valida o registro central de rotas Vitrine IA Pro")
    parser.add_argument("registry", nargs="?", default="routes.json")
    args = parser.parse_args()
    try:
        data, errors, warnings = load_and_validate(args.registry)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"ERRO: {exc}", file=sys.stderr)
        return 2
    for warning in warnings:
        print(f"AVISO: {warning}")
    if errors:
        for error in errors:
            print(f"ERRO: {error}", file=sys.stderr)
        return 1
    print(f"OK: {len(data.get('routes', []))} rotas validas; network={data['network']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
