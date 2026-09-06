from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def tool_record(path: Path, node: ast.FunctionDef) -> dict[str, object] | None:
    for decorator in node.decorator_list:
        if not isinstance(decorator, ast.Call):
            continue
        fn = decorator.func
        if not (
            isinstance(fn, ast.Attribute)
            and isinstance(fn.value, ast.Name)
            and fn.value.id == "mcp"
            and fn.attr == "tool"
        ):
            continue
        read_only = None
        destructive = None
        for keyword in decorator.keywords:
            if keyword.arg != "annotations" or not isinstance(keyword.value, ast.Dict):
                continue
            annotations = {}
            for key, value in zip(keyword.value.keys, keyword.value.values):
                if isinstance(key, ast.Constant) and isinstance(key.value, str) and isinstance(value, ast.Constant):
                    annotations[key.value] = value.value
            read_only = annotations.get("readOnlyHint")
            destructive = annotations.get("destructiveHint")
        return {
            "name": node.name,
            "file": path.name,
            "read_only": read_only,
            "destructive": destructive,
        }
    return None


def main() -> int:
    records: list[dict[str, object]] = []
    for path in sorted(ROOT.glob("*.py")):
        if path.name in {"static_catalog_audit.py", "build_candidate.py", "vendor_historical_sources.py"}:
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                item = tool_record(path, node)
                if item:
                    records.append(item)

    names = [str(item["name"]) for item in records]
    duplicates = sorted({name for name in names if names.count(name) > 1})
    read_only = sorted(str(item["name"]) for item in records if item["read_only"] is True)
    operational = sorted(str(item["name"]) for item in records if item["read_only"] is False)
    unspecified = sorted(str(item["name"]) for item in records if item["read_only"] is None)

    result = {
        "static_scope": str(ROOT),
        "tool_count": len(records),
        "read_only_count": len(read_only),
        "operational_count": len(operational),
        "unspecified_count": len(unspecified),
        "duplicates": duplicates,
        "read_only": read_only,
        "operational": operational,
        "unspecified": unspecified,
        "records": records,
        "note": "Static source audit only; the authoritative gate remains MCP tools/list on the isolated candidate runtime.",
    }
    print(json.dumps(result, indent=2, ensure_ascii=False))
    if duplicates:
        raise SystemExit("duplicate MCP tool names detected")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
