from __future__ import annotations

import hashlib
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent

SOURCES = {
    "supervisor.py": "https://raw.githubusercontent.com/cschibelsky-star/vitrine-ai-pro/c5980a4b23f0a22868658da04dea009bd9910aa3/services/vps-mcp-connector/supervisor.py",
    "workflow_catalog.py": "https://raw.githubusercontent.com/cschibelsky-star/vitrine-ai-pro/c5980a4b23f0a22868658da04dea009bd9910aa3/services/vps-mcp-connector/workflow_catalog.py",
    "factory_kernel.py": "https://raw.githubusercontent.com/cschibelsky-star/vitrine-ai-pro/c5980a4b23f0a22868658da04dea009bd9910aa3/services/vps-mcp-connector/factory_kernel.py",
    "ai_dev_hub_tools.py": "https://raw.githubusercontent.com/cschibelsky-star/Vitrine-IA-Pro-VPS/c680693fe925d48830b3b27c2b350ec6fae013d4/connector-v2/ai_dev_hub_tools.py",
}


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "vitrine-vps-ops-recovery/1"})
    with urllib.request.urlopen(req, timeout=30) as response:
        data = response.read()
    if not data:
        raise RuntimeError(f"empty source: {url}")
    return data


def main() -> int:
    for name, url in SOURCES.items():
        data = fetch(url)
        target = HERE / name
        target.write_bytes(data)
        print(f"PINNED_LAYER={name} SHA256={hashlib.sha256(data).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
