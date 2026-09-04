from __future__ import annotations

import ipaddress
import json
import os
import shutil
import socket
import ssl
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

NGINX_ROOT = Path(os.getenv("PRODUCTION_NGINX_ROOT", "/srv/vitrine/docker/nginx/conf.d")).resolve()
SSL_ROOT = Path(os.getenv("PRODUCTION_SSL_ROOT", "/srv/vitrine/ssl")).resolve()
ACME_WEBROOT = Path(os.getenv("PRODUCTION_ACME_WEBROOT", "/srv/vitrine/docker/nginx/html")).resolve()
STATE_ROOT = Path(os.getenv("PRODUCTION_PUBLICATION_STATE_ROOT", "/var/log/vitrine-ops-v5/production-publications")).resolve()
PUBLIC_GATEWAY = os.getenv("PRODUCTION_PUBLIC_GATEWAY", "vitrine_nginx").strip() or "vitrine_nginx"
CERTBOT_IMAGE = os.getenv("PRODUCTION_CERTBOT_IMAGE", "certbot/certbot:latest").strip() or "certbot/certbot:latest"
CERTBOT_EMAIL = os.getenv("PRODUCTION_CERTBOT_EMAIL", "vitrineiapro@gmail.com").strip() or "vitrineiapro@gmail.com"
DNS_PROVIDER = os.getenv("PRODUCTION_DNS_PROVIDER", "disabled").strip().lower() or "disabled"
CF_TOKEN = os.getenv("PRODUCTION_DNS_CLOUDFLARE_API_TOKEN", "").strip()
CF_ZONE_ID = os.getenv("PRODUCTION_DNS_CLOUDFLARE_ZONE_ID", "").strip()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _valid_route_id(route_id: str) -> str:
    value = str(route_id or "").strip().lower()
    if not value or any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-_" for ch in value):
        raise ValueError("invalid_route_id")
    return value


def _valid_hostname(hostname: str) -> str:
    value = str(hostname or "").strip().lower().rstrip(".")
    if not value or len(value) > 253 or value.startswith("-") or value.endswith("-"):
        raise ValueError("invalid_hostname")
    labels = value.split(".")
    if len(labels) < 2:
        raise ValueError("invalid_hostname")
    for label in labels:
        if not label or len(label) > 63 or label.startswith("-") or label.endswith("-"):
            raise ValueError("invalid_hostname")
        if any(ch not in "abcdefghijklmnopqrstuvwxyz0123456789-" for ch in label):
            raise ValueError("invalid_hostname")
    return value


def _valid_upstream(upstream: str) -> str:
    value = str(upstream or "").strip()
    if value.startswith("http://"):
        value = value[7:]
    if value.startswith("https://") or "/" in value or "@" in value or "?" in value or "#" in value:
        raise ValueError("invalid_upstream")
    host, sep, port = value.rpartition(":")
    if not sep or not host or not port.isdigit():
        raise ValueError("invalid_upstream")
    p = int(port)
    if p < 1 or p > 65535:
        raise ValueError("invalid_upstream")
    if any(ch not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_." for ch in host):
        raise ValueError("invalid_upstream")
    return f"{host}:{p}"


def _safe_state_path(route_id: str) -> Path:
    route_id = _valid_route_id(route_id)
    STATE_ROOT.mkdir(parents=True, exist_ok=True)
    path = (STATE_ROOT / f"{route_id}.json").resolve()
    if STATE_ROOT != path.parent:
        raise PermissionError("state_path_blocked")
    return path


def _read_state(route_id: str) -> dict[str, Any]:
    path = _safe_state_path(route_id)
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_state(route_id: str, data: dict[str, Any]) -> None:
    path = _safe_state_path(route_id)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def _resolve_ipv4(hostname: str) -> list[str]:
    values: list[str] = []
    try:
        for item in socket.getaddrinfo(hostname, 443, socket.AF_INET, socket.SOCK_STREAM):
            ip = item[4][0]
            if ip not in values:
                values.append(ip)
    except socket.gaierror:
        pass
    return values


def _dns_provider_status() -> dict[str, Any]:
    if DNS_PROVIDER == "cloudflare":
        configured = bool(CF_TOKEN and CF_ZONE_ID)
        return {"provider": "cloudflare", "configured": configured, "write_enabled": configured}
    return {"provider": DNS_PROVIDER, "configured": False, "write_enabled": False}


def _cf_request(method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
    if DNS_PROVIDER != "cloudflare" or not CF_TOKEN or not CF_ZONE_ID:
        raise PermissionError("dns_writer_not_configured")
    url = f"https://api.cloudflare.com/client/v4{path}"
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json", "User-Agent": "vitrine-mcp-v5/production-publication"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"dns_provider_request_failed:{type(exc).__name__}") from exc
    if not data.get("success"):
        raise RuntimeError("dns_provider_rejected")
    return data


def _cf_find_a_record(hostname: str) -> dict[str, Any] | None:
    quoted = urllib.parse.quote(hostname, safe="") if hasattr(urllib, "parse") else hostname
    data = _cf_request("GET", f"/zones/{CF_ZONE_ID}/dns_records?type=A&name={quoted}")
    result = data.get("result") or []
    return result[0] if result else None


def _dns_set_a(hostname: str, target_ip: str, ttl: int = 300) -> dict[str, Any]:
    ipaddress.ip_address(target_ip)
    if DNS_PROVIDER != "cloudflare":
        raise PermissionError("dns_writer_not_configured")
    current = _cf_find_a_record(hostname)
    payload = {"type": "A", "name": hostname, "content": target_ip, "ttl": max(60, min(int(ttl), 86400)), "proxied": False}
    if current:
        data = _cf_request("PUT", f"/zones/{CF_ZONE_ID}/dns_records/{current['id']}", payload)
        action = "updated"
    else:
        data = _cf_request("POST", f"/zones/{CF_ZONE_ID}/dns_records", payload)
        action = "created"
    result = data.get("result") or {}
    return {"ok": True, "action": action, "record_id": result.get("id"), "name": hostname, "content": result.get("content", target_ip), "ttl": result.get("ttl", payload["ttl"])}


def _nginx_http(hostname: str, upstream: str) -> str:
    return f'''server {{
    listen 80;
    listen [::]:80;
    server_name {hostname};

    location ^~ /.well-known/acme-challenge/ {{
        root /usr/share/nginx/html;
        default_type text/plain;
        try_files $uri =404;
    }}

    location / {{
        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
'''


def _nginx_https(hostname: str, upstream: str) -> str:
    return f'''server {{
    listen 80;
    listen [::]:80;
    server_name {hostname};

    location ^~ /.well-known/acme-challenge/ {{
        root /usr/share/nginx/html;
        default_type text/plain;
        try_files $uri =404;
    }}

    location / {{
        return 301 https://$host$request_uri;
    }}
}}

server {{
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name {hostname};

    ssl_certificate /etc/letsencrypt/live/{hostname}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{hostname}/privkey.pem;

    location / {{
        proxy_pass http://{upstream};
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}
'''


def _http_probe(url: str, timeout: int = 10) -> dict[str, Any]:
    req = urllib.request.Request(url, headers={"User-Agent": "vitrine-mcp-v5/production-publication"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            return {"ok": 200 <= response.status < 400, "status_code": response.status, "final_url": response.geturl()}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "status_code": exc.code, "error": "http_error"}
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "error": type(exc).__name__}


def register_production_publication_tools(
    mcp: Any,
    project_paths: Callable[[str], tuple[dict[str, Any], Path, Path]],
    audit: Callable[[str, dict[str, Any], dict[str, Any]], None],
    run: Callable[..., dict[str, Any]],
) -> None:
    def route_data(route_id: str) -> tuple[dict[str, Any], Path]:
        normalized = _valid_route_id(route_id)
        _, _, repository = project_paths("vitrine-ia-pro-vps")
        registry = repository / "routing" / "routes.json"
        if not registry.is_file():
            raise FileNotFoundError("routing_registry_missing")
        payload = json.loads(registry.read_text(encoding="utf-8"))
        route = next((item for item in payload.get("routes", []) if item.get("id") == normalized), None)
        if route is None:
            raise FileNotFoundError("route_not_registered")
        if route.get("environment") != "production":
            raise PermissionError("route_environment_not_production")
        if route.get("ssl") is not True:
            raise PermissionError("route_ssl_required")
        hostname = _valid_hostname(route.get("hostname", ""))
        upstream = _valid_upstream(route.get("upstream", ""))
        route = {**route, "hostname": hostname, "upstream": upstream}
        return route, repository

    def nginx_path(route_id: str) -> Path:
        normalized = _valid_route_id(route_id)
        path = (NGINX_ROOT / f"{normalized}.conf").resolve()
        if path.parent != NGINX_ROOT:
            raise PermissionError("nginx_path_blocked")
        return path

    def nginx_apply(route_id: str, content: str) -> dict[str, Any]:
        path = nginx_path(route_id)
        NGINX_ROOT.mkdir(parents=True, exist_ok=True)
        backup = None
        if path.is_file():
            backup = path.with_name(f".{path.name}.bak-{_stamp()}")
            shutil.copy2(path, backup)
        tmp = path.with_name(f".{path.name}.tmp")
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, path)
        test = run(["docker", "exec", PUBLIC_GATEWAY, "nginx", "-t"], Path("/"), timeout=60)
        if not test.get("ok"):
            if backup and backup.is_file():
                shutil.copy2(backup, path)
            elif path.exists():
                path.unlink()
            return {"ok": False, "error": "nginx_test_failed", "detail": test, "backup": str(backup) if backup else None}
        reload_result = run(["docker", "exec", PUBLIC_GATEWAY, "nginx", "-s", "reload"], Path("/"), timeout=60)
        if not reload_result.get("ok"):
            if backup and backup.is_file():
                shutil.copy2(backup, path)
                run(["docker", "exec", PUBLIC_GATEWAY, "nginx", "-s", "reload"], Path("/"), timeout=60)
            return {"ok": False, "error": "nginx_reload_failed", "detail": reload_result, "backup": str(backup) if backup else None}
        return {"ok": True, "path": str(path), "backup": str(backup) if backup else None}

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def production_publication_plan(route_id: str, target_ip: str = "") -> dict[str, Any]:
        try:
            route, _ = route_data(route_id)
        except (FileNotFoundError, PermissionError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
        current_ips = _resolve_ipv4(route["hostname"])
        provider = _dns_provider_status()
        result = {
            "ok": True,
            "route_id": route["id"],
            "hostname": route["hostname"],
            "upstream": route["upstream"],
            "current_a": current_ips,
            "target_ip": target_ip or None,
            "dns": provider,
            "stages": ["preflight", "nginx_http_acme", "dns_cutover", "certificate_issue", "nginx_https", "validation", "activate_registry"],
            "rollback": ["restore_dns", "restore_nginx", "reload_gateway"],
            "will_execute": False,
        }
        audit("production_publication_plan", {"route_id": route["id"]}, {"ok": True, "dns_provider": provider.get("provider")})
        return result

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def production_publication_preflight(route_id: str, target_ip: str) -> dict[str, Any]:
        try:
            route, _ = route_data(route_id)
            ipaddress.ip_address(target_ip)
        except (FileNotFoundError, PermissionError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
        upstream_url = f"http://{route['upstream']}{route.get('health_path') or '/'}"
        upstream = _http_probe(upstream_url)
        gateway = run(["docker", "inspect", PUBLIC_GATEWAY], Path("/"), timeout=30)
        cert_path = SSL_ROOT / "live" / route["hostname"] / "fullchain.pem"
        provider = _dns_provider_status()
        result = {
            "ok": bool(upstream.get("ok")) and bool(gateway.get("ok")),
            "route_id": route["id"],
            "hostname": route["hostname"],
            "upstream": upstream,
            "gateway_available": bool(gateway.get("ok")),
            "certificate_present": cert_path.is_file(),
            "current_a": _resolve_ipv4(route["hostname"]),
            "target_ip": target_ip,
            "dns": provider,
            "dns_write_ready": bool(provider.get("write_enabled")),
        }
        if not provider.get("write_enabled"):
            result["warning"] = "dns_writer_not_configured"
        audit("production_publication_preflight", {"route_id": route["id"], "target_ip": target_ip}, {"ok": result["ok"], "dns_write_ready": result["dns_write_ready"]})
        return result

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    def production_nginx_prepare(route_id: str, confirm: str = "") -> dict[str, Any]:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
        try:
            route, _ = route_data(route_id)
        except (FileNotFoundError, PermissionError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
        result = nginx_apply(route["id"], _nginx_http(route["hostname"], route["upstream"]))
        state = _read_state(route["id"])
        state.update({"route_id": route["id"], "hostname": route["hostname"], "upstream": route["upstream"], "nginx_backup": result.get("backup"), "stage": "nginx_http_acme" if result.get("ok") else "failed", "updated_at": _now()})
        _write_state(route["id"], state)
        audit("production_nginx_prepare", {"route_id": route["id"]}, {"ok": result.get("ok", False), "backup": result.get("backup")})
        return {**result, "route_id": route["id"], "hostname": route["hostname"]}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    def production_dns_cutover(route_id: str, target_ip: str, ttl: int = 300, confirm: str = "") -> dict[str, Any]:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
        try:
            route, _ = route_data(route_id)
            ipaddress.ip_address(target_ip)
            previous = _resolve_ipv4(route["hostname"])
            result = _dns_set_a(route["hostname"], target_ip, ttl)
        except (FileNotFoundError, PermissionError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "route_id": str(route_id or ""), "dns": _dns_provider_status()}
        state = _read_state(route["id"])
        state.update({"route_id": route["id"], "hostname": route["hostname"], "previous_a": previous, "target_ip": target_ip, "stage": "dns_cutover", "updated_at": _now()})
        _write_state(route["id"], state)
        audit("production_dns_cutover", {"route_id": route["id"], "hostname": route["hostname"], "target_ip": target_ip}, {"ok": True, "previous_a": previous})
        return {**result, "route_id": route["id"], "previous_a": previous, "target_ip": target_ip}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    def production_certificate_issue(route_id: str, confirm: str = "") -> dict[str, Any]:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
        try:
            route, _ = route_data(route_id)
        except (FileNotFoundError, PermissionError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
        SSL_ROOT.mkdir(parents=True, exist_ok=True)
        ACME_WEBROOT.mkdir(parents=True, exist_ok=True)
        cmd = [
            "docker", "run", "--rm", "--network", "bridge",
            "-v", f"{SSL_ROOT}:/etc/letsencrypt",
            "-v", f"{ACME_WEBROOT}:/var/www/html",
            CERTBOT_IMAGE,
            "certonly", "--webroot", "-w", "/var/www/html",
            "-d", route["hostname"], "--non-interactive", "--agree-tos",
            "--email", CERTBOT_EMAIL, "--keep-until-expiring",
        ]
        result = run(cmd, Path("/"), timeout=1200)
        cert = SSL_ROOT / "live" / route["hostname"] / "fullchain.pem"
        ok = bool(result.get("ok")) and cert.is_file()
        response = {"ok": ok, "route_id": route["id"], "hostname": route["hostname"], "certificate_present": cert.is_file(), "exit_code": result.get("exit_code"), "stdout": str(result.get("stdout") or "")[-8000:], "stderr": str(result.get("stderr") or "")[-4000:]}
        if ok:
            state = _read_state(route["id"])
            state.update({"stage": "certificate_issued", "updated_at": _now()})
            _write_state(route["id"], state)
        audit("production_certificate_issue", {"route_id": route["id"], "hostname": route["hostname"]}, {"ok": ok, "exit_code": result.get("exit_code")})
        return response

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    def production_https_activate(route_id: str, confirm: str = "") -> dict[str, Any]:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
        try:
            route, _ = route_data(route_id)
        except (FileNotFoundError, PermissionError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
        cert = SSL_ROOT / "live" / route["hostname"] / "fullchain.pem"
        key = SSL_ROOT / "live" / route["hostname"] / "privkey.pem"
        if not cert.is_file() or not key.is_file():
            return {"ok": False, "error": "certificate_missing", "route_id": route["id"], "hostname": route["hostname"]}
        result = nginx_apply(route["id"], _nginx_https(route["hostname"], route["upstream"]))
        state = _read_state(route["id"])
        state.update({"stage": "nginx_https" if result.get("ok") else "failed", "updated_at": _now()})
        _write_state(route["id"], state)
        audit("production_https_activate", {"route_id": route["id"]}, {"ok": result.get("ok", False)})
        return {**result, "route_id": route["id"], "hostname": route["hostname"]}

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False})
    def production_publication_validate(route_id: str, target_ip: str = "") -> dict[str, Any]:
        try:
            route, _ = route_data(route_id)
        except (FileNotFoundError, PermissionError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
        dns = _resolve_ipv4(route["hostname"])
        http = _http_probe(f"http://{route['hostname']}")
        https = _http_probe(f"https://{route['hostname']}")
        cert_ok = False
        cert_subject = None
        try:
            context = ssl.create_default_context()
            with socket.create_connection((route["hostname"], 443), timeout=8) as raw:
                with context.wrap_socket(raw, server_hostname=route["hostname"]) as tls:
                    cert = tls.getpeercert()
                    cert_ok = True
                    cert_subject = dict(x[0] for x in cert.get("subject", []))
        except (OSError, ssl.SSLError):
            cert_ok = False
        target_matches = True if not target_ip else target_ip in dns
        ok = bool(http.get("ok")) and bool(https.get("ok")) and cert_ok and target_matches
        result = {"ok": ok, "route_id": route["id"], "hostname": route["hostname"], "dns_a": dns, "target_ip": target_ip or None, "target_matches": target_matches, "http": http, "https": https, "tls_valid": cert_ok, "tls_subject": cert_subject, "state": _read_state(route["id"])}
        audit("production_publication_validate", {"route_id": route["id"], "target_ip": target_ip}, {"ok": ok, "dns_a": dns, "tls_valid": cert_ok})
        return result

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    def production_publication_rollback(route_id: str, confirm: str = "") -> dict[str, Any]:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
        try:
            route, _ = route_data(route_id)
        except (FileNotFoundError, PermissionError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "error": str(exc), "route_id": str(route_id or "")}
        state = _read_state(route["id"])
        path = nginx_path(route["id"])
        nginx_restored = False
        backup_value = state.get("nginx_backup")
        if backup_value:
            backup = Path(str(backup_value)).resolve()
            if backup.parent == NGINX_ROOT and backup.is_file():
                shutil.copy2(backup, path)
                nginx_restored = True
        elif path.is_file():
            path.unlink()
            nginx_restored = True
        nginx_test = run(["docker", "exec", PUBLIC_GATEWAY, "nginx", "-t"], Path("/"), timeout=60)
        nginx_reload = run(["docker", "exec", PUBLIC_GATEWAY, "nginx", "-s", "reload"], Path("/"), timeout=60) if nginx_test.get("ok") else {"ok": False, "error": "nginx_test_failed"}
        dns_result: dict[str, Any] = {"ok": True, "status": "not_changed"}
        previous = state.get("previous_a") or []
        if previous and state.get("target_ip"):
            try:
                dns_result = _dns_set_a(route["hostname"], previous[0], 300)
            except (PermissionError, RuntimeError, ValueError) as exc:
                dns_result = {"ok": False, "error": str(exc)}
        ok = bool(nginx_test.get("ok")) and bool(nginx_reload.get("ok")) and bool(dns_result.get("ok"))
        state.update({"stage": "rolled_back" if ok else "rollback_incomplete", "updated_at": _now()})
        _write_state(route["id"], state)
        audit("production_publication_rollback", {"route_id": route["id"]}, {"ok": ok, "nginx_restored": nginx_restored, "dns_ok": dns_result.get("ok")})
        return {"ok": ok, "route_id": route["id"], "nginx_restored": nginx_restored, "nginx_test": nginx_test, "nginx_reload": nginx_reload, "dns": dns_result}

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True})
    def production_publication_execute(route_id: str, target_ip: str, confirm: str = "") -> dict[str, Any]:
        if confirm != "EXECUTAR":
            return {"ok": False, "error": "confirmation_required", "required": "EXECUTAR"}
        pre = production_publication_preflight(route_id, target_ip)
        if not pre.get("ok"):
            return {"ok": False, "error": "preflight_failed", "preflight": pre}
        if not pre.get("dns_write_ready"):
            return {"ok": False, "error": "dns_writer_not_configured", "preflight": pre, "safe_stop": True}
        nginx = production_nginx_prepare(route_id, confirm="EXECUTAR")
        if not nginx.get("ok"):
            return {"ok": False, "error": "nginx_prepare_failed", "nginx": nginx}
        dns = production_dns_cutover(route_id, target_ip, confirm="EXECUTAR")
        if not dns.get("ok"):
            production_publication_rollback(route_id, confirm="EXECUTAR")
            return {"ok": False, "error": "dns_cutover_failed", "dns": dns, "rolled_back": True}
        route, _ = route_data(route_id)
        propagated = False
        for _ in range(12):
            if target_ip in _resolve_ipv4(route["hostname"]):
                propagated = True
                break
            import time
            time.sleep(5)
        if not propagated:
            production_publication_rollback(route_id, confirm="EXECUTAR")
            return {"ok": False, "error": "dns_propagation_timeout", "rolled_back": True}
        cert = production_certificate_issue(route_id, confirm="EXECUTAR")
        if not cert.get("ok"):
            production_publication_rollback(route_id, confirm="EXECUTAR")
            return {"ok": False, "error": "certificate_issue_failed", "certificate": cert, "rolled_back": True}
        https = production_https_activate(route_id, confirm="EXECUTAR")
        if not https.get("ok"):
            production_publication_rollback(route_id, confirm="EXECUTAR")
            return {"ok": False, "error": "https_activate_failed", "https": https, "rolled_back": True}
        validation = production_publication_validate(route_id, target_ip)
        if not validation.get("ok"):
            production_publication_rollback(route_id, confirm="EXECUTAR")
            return {"ok": False, "error": "validation_failed", "validation": validation, "rolled_back": True}
        state = _read_state(route_id)
        state.update({"stage": "active", "status": "active", "validated_at": _now(), "updated_at": _now()})
        _write_state(route_id, state)
        audit("production_publication_execute", {"route_id": route_id, "target_ip": target_ip}, {"ok": True, "status": "active"})
        return {"ok": True, "route_id": route_id, "target_ip": target_ip, "nginx": nginx, "dns": dns, "certificate": cert, "https": https, "validation": validation, "status": "active"}
