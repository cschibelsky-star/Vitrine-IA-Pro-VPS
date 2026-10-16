"""Fail-closed, scoped Factory Asset Host grant for the protected V5 runtime.

This is deliberately applied AFTER the existing publication guard. The current
protected runtime image remains the base, so unrelated operational overlays do
not need to be reconstructed from a divergent checkout.
"""
from __future__ import annotations

import ast

ANCHOR = "CONTROLLED_COMPOSE_POLICY: dict[str, dict[str, Any]] = {\n"
ENTRY = '''    "factory-asset-intake-validation-20261015": {
        "compose_files": {"docker-compose.asset-validation.yml", "docker-compose.asset-host.yml"},
        "services": {"asset-validation", "asset-host"},
        "run_once": {"asset-validation"},
        "build": {"asset-validation", "asset-host"},
        "up": {"asset-host"},
    },
'''


def apply(source: str) -> str:
    if source.count(ANCHOR) != 1:
        raise RuntimeError("asset_host_policy_anchor_count_invalid")
    if '"factory-asset-intake-validation-20261015"' in source:
        raise RuntimeError("asset_host_policy_already_present")
    updated = source.replace(ANCHOR, ANCHOR + ENTRY, 1)
    ast.parse(updated)
    return updated
