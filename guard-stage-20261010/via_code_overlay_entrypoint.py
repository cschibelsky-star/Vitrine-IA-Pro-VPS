"""Isolated candidate: extend the *currently installed* V5 image without replacing it.

The existing /app/main_ext.py owns the original connector and publication guards.
We execute it as a non-__main__ module, then register exactly one new experiment
tool; fail closed if the existing loader's interface is not compatible.
"""
from __future__ import annotations
import runpy
import sys
from pathlib import Path

path=Path("/app/main_ext.py")
if not path.is_file():
    raise RuntimeError("v5_existing_entrypoint_missing")

ns=runpy.run_path(str(path),run_name="v5_existing_runtime")
mcp=ns.get("mcp")
core=sys.modules.get("main")
if mcp is None or core is None:
    raise RuntimeError("v5_existing_runtime_not_compatible")
if not hasattr(core,"_project_paths") or not hasattr(core,"_audit"):
    raise RuntimeError("v5_required_safe_helpers_missing")

from via_code_pilot_tool import register
register(mcp,core)

if __name__=="__main__":
    mcp.run(transport="http",host="0.0.0.0",port=8000)
