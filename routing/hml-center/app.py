#!/usr/bin/env python3
import base64
import hmac
import json
import os
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

REGISTRY = Path(os.getenv("ROUTING_REGISTRY", "/app/routes.json"))
USER = os.getenv("HML_CENTER_USER", "")
PASSWORD = os.getenv("HML_CENTER_PASSWORD", "")
PORT = int(os.getenv("PORT", "8080"))

PROJECT_NAMES = {
    "vitrine-hml-center": "Central de Homologacao",
    "tvsumare": "TV Sumare Enterprise",
    "cursos-ia-mvp": "Cursos IA MVP",
    "agente-compras-ia": "Agente Compras IA",
}

STATUS_LABELS = {
    "active": "Ativo",
    "pending_dns_proxy": "Aguardando DNS/Proxy",
    "pending_app": "Aguardando aplicacao",
    "disabled": "Desativado",
}


def load_routes():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    return [r for r in data.get("routes", []) if r.get("environment") == "homologation"]


def authorized(header):
    if not USER or not PASSWORD or not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
        supplied_user, supplied_password = decoded.split(":", 1)
    except (ValueError, UnicodeDecodeError):
        return False
    return hmac.compare_digest(supplied_user, USER) and hmac.compare_digest(supplied_password, PASSWORD)


def page():
    rows = []
    for route in load_routes():
        project_id = route.get("project_id", "")
        hostname = route.get("hostname", "")
        status = route.get("status", "")
        name = PROJECT_NAMES.get(project_id, project_id.replace("-", " ").title())
        url = f"https://{hostname}"
        rows.append(
            "<article class='card'>"
            f"<div><span class='eyebrow'>HOMOLOGACAO</span><h2>{escape(name)}</h2>"
            f"<p>{escape(hostname)}</p></div>"
            f"<div class='actions'><span class='status status-{escape(status)}'>{escape(STATUS_LABELS.get(status, status))}</span>"
            f"<a href='{escape(url)}' target='_blank' rel='noopener'>Abrir HML</a></div>"
            "</article>"
        )
    cards = "".join(rows) or "<p>Nenhum projeto de homologacao registrado.</p>"
    return f"""<!doctype html>
<html lang='pt-BR'>
<head>
<meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>Vitrine IA Pro | Homologacao</title>
<style>
:root {{ color-scheme: light; font-family: Inter, system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; }}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:#f5f7fb; color:#172033; }}
header {{ padding:42px 24px 28px; background:#fff; border-bottom:1px solid #e5e9f0; }}
main, .inner {{ width:min(1100px, calc(100% - 32px)); margin:auto; }}
h1 {{ margin:6px 0 8px; font-size:clamp(28px,4vw,44px); }}
.lead {{ margin:0; color:#647087; }}
.grid {{ display:grid; gap:14px; padding:28px 0 48px; }}
.card {{ display:flex; align-items:center; justify-content:space-between; gap:18px; background:#fff; border:1px solid #e1e6ef; border-radius:16px; padding:20px; box-shadow:0 8px 24px rgba(30,45,70,.05); }}
.card h2 {{ margin:5px 0 4px; font-size:20px; }} .card p {{ margin:0; color:#6a7588; }}
.eyebrow {{ font-size:11px; font-weight:800; letter-spacing:.12em; color:#506078; }}
.actions {{ display:flex; align-items:center; gap:12px; flex-wrap:wrap; justify-content:flex-end; }}
a {{ text-decoration:none; background:#172033; color:#fff; padding:10px 14px; border-radius:10px; font-weight:700; }}
.status {{ padding:7px 10px; border-radius:999px; background:#eef2f7; font-size:12px; font-weight:800; }}
.status-active {{ background:#e8f7ed; color:#176a37; }}
.status-pending_dns_proxy,.status-pending_app {{ background:#fff3d8; color:#875b00; }}
.status-disabled {{ background:#f3e8e8; color:#8d3030; }}
footer {{ color:#7b8697; font-size:12px; padding:0 0 28px; }}
@media(max-width:700px) {{ .card {{ align-items:flex-start; flex-direction:column; }} .actions {{ justify-content:flex-start; }} }}
</style></head>
<body><header><div class='inner'><span class='eyebrow'>VITRINE IA PRO</span><h1>Central de Homologacao</h1><p class='lead'>Ambientes tecnicos de validacao antes de producao.</p></div></header>
<main><section class='grid'>{cards}</section><footer>Ambiente restrito. URLs de producao e dados internos nao sao exibidos neste painel.</footer></main></body></html>"""


class Handler(BaseHTTPRequestHandler):
    server_version = "VitrineHML/1.0"

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            self.send_response(200)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(b"OK\n")
            return
        if path != "/":
            self.send_error(404)
            return
        if not authorized(self.headers.get("Authorization")):
            self.send_response(401)
            self.send_header("WWW-Authenticate", 'Basic realm="Vitrine IA Pro HML"')
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            return
        try:
            body = page().encode("utf-8")
        except Exception:
            self.send_error(503, "Routing registry unavailable")
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        print(f"{self.address_string()} - {fmt % args}")


if __name__ == "__main__":
    if not USER or not PASSWORD:
        raise SystemExit("HML_CENTER_USER e HML_CENTER_PASSWORD sao obrigatorios")
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
