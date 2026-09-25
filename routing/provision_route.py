#!/usr/bin/env python3
"""Collision-safe route identity allocator for Vitrine IA Pro Factory."""

import argparse
import fcntl
import json
import os
import re
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REGISTRY = ROOT / "routes.json"
LOCK = ROOT / ".routes.lock"

def slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9-]+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-")
    if not value:
        raise ValueError("friendly slug is empty")
    return value

def allocate(kind: str, project_id: str, upstream: str, health_path: str, friendly: str | None):
    with LOCK.open("a+") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        data = json.loads(REGISTRY.read_text())
        policy = data["code_policy"]
        is_project = kind == "project"
        prefix = policy["project_prefix"] if is_project else policy["customer_prefix"]
        counter_key = "project_next" if is_project else "customer_next"
        width = int(policy["width"])
        number = int(policy[counter_key])
        code = f"{prefix}{number:0{width}d}"

        existing_hosts = set()
        existing_codes = set()
        for route in data["routes"]:
            if route.get("deployment_code"):
                existing_codes.add(route["deployment_code"])
            if route.get("customer_code"):
                existing_codes.add(route["customer_code"])
            existing_hosts.add(route.get("hostname"))
            existing_hosts.update(route.get("friendly_aliases", []))
            existing_hosts.update(route.get("legacy_aliases", []))

        while code in existing_codes:
            number += 1
            code = f"{prefix}{number:0{width}d}"

        if is_project:
            hostname = f"{code}.{data['base_domains']['homologation']}"
            environment = "homologation"
            route_id = f"{code}-hml"
            identity_key = "deployment_code"
        else:
            hostname = f"{code}.{data['base_domains']['customer_root']}"
            environment = "production"
            route_id = code
            identity_key = "customer_code"

        aliases = []
        if friendly:
            friendly_slug = slug(friendly)
            if is_project:
                alias = f"{friendly_slug}.{data['base_domains']['homologation']}"
            else:
                if friendly_slug in set(data.get("reserved_root_labels", [])):
                    raise ValueError(f"friendly alias is reserved: {friendly_slug}")
                alias = f"{friendly_slug}.{data['base_domains']['customer_root']}"
            if alias in existing_hosts:
                raise ValueError(f"hostname/alias already reserved: {alias}")
            aliases.append(alias)

        if hostname in existing_hosts:
            raise ValueError(f"technical hostname already reserved: {hostname}")

        route = {
            "id": route_id,
            "project_id": project_id,
            identity_key: code,
            "environment": environment,
            "hostname": hostname,
            "friendly_aliases": aliases,
            "legacy_aliases": [],
            "upstream": upstream,
            "health_path": health_path,
            "ssl": True,
            "status": "planned",
            "legacy": False,
        }
        data["routes"].append(route)
        policy[counter_key] = number + 1

        fd, temp_name = tempfile.mkstemp(prefix="routes.", suffix=".json", dir=ROOT)
        try:
            with os.fdopen(fd, "w") as temp:
                json.dump(data, temp, indent=2, ensure_ascii=False)
                temp.write("\n")
                temp.flush()
                os.fsync(temp.fileno())
            os.replace(temp_name, REGISTRY)
        finally:
            if os.path.exists(temp_name):
                os.unlink(temp_name)

        print(json.dumps(route, ensure_ascii=False))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--kind", choices=["project", "customer"], required=True)
    parser.add_argument("--project-id", required=True)
    parser.add_argument("--upstream", required=True)
    parser.add_argument("--health-path", default="/health")
    parser.add_argument("--friendly")
    args = parser.parse_args()
    allocate(args.kind, args.project_id, args.upstream, args.health_path, args.friendly)

if __name__ == "__main__":
    main()
