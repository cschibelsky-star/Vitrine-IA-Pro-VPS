"""Generate minimal source overlays, preserving unrelated runtime extensions."""
from __future__ import annotations

import ast
from pathlib import Path

GUARDED = {
    "project_clone", "project_git_reconcile_to_origin", "git_reconcile", "git_checkout",
    "project_materialize", "project_bootstrap_from_git", "project_compose_service_execute",
    "project_manifest_branch_configure",
}
BROKER_HELPERS = {
    "PublicationProjectRequest", "load_publication_sources", "canonical_source_preflight",
    "publication_preflight", "publication_lock", "project_clone", "project_clone_locked",
}


def node_start(node):
    return min([node.lineno] + [d.lineno for d in getattr(node, "decorator_list", [])])


def broker_overlay(existing: str, reviewed: str) -> str:
    tree = ast.parse(existing)
    clone = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "project_clone"]
    if len(clone) != 1:
        raise ValueError("expected one clone executor")
    if any(getattr(n, "name", None) in BROKER_HELPERS - {"project_clone"} for n in tree.body):
        raise ValueError("gate already present; compare reviewed version before replacing")
    lines = existing.splitlines(keepends=True)
    candidate = ast.parse(reviewed)
    additions = []
    reviewed_lines = reviewed.splitlines(keepends=True)
    for node in candidate.body:
        if getattr(node, "name", None) in BROKER_HELPERS:
            additions.append("".join(reviewed_lines[node_start(node)-1:node.end_lineno]))
    patched = "".join(lines[:node_start(clone[0])-1]) + "\n\n".join(additions) + "\n\n" + "".join(lines[clone[0].end_lineno:])
    anchor = "from __future__ import annotations\n"
    if patched.count(anchor) != 1:
        raise ValueError("future import missing")
    patched = patched.replace(anchor, anchor + "import hashlib\nimport fcntl\nimport re\nimport urllib.request\nfrom contextlib import contextmanager\n", 1)
    compile(patched, "broker-overlay", "exec")
    return patched


def independent_overlay(existing: str, loader_expression: str) -> tuple[str, list[str]]:
    if "runtime_publication_guard" in existing:
        raise ValueError("adapter already present")
    tree = ast.parse(existing)
    lines = existing.splitlines(keepends=True)
    insertions = []
    names = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.name not in GUARDED:
            continue
        args = {arg.arg for arg in node.args.args}
        if "project_id" not in args:
            raise ValueError("unsupported guarded signature")
        operation = "operation" if "operation" in args else "''"
        workspace = "workspace_root" if node.name == "project_bootstrap_from_git" else "''"
        body = node.body
        first = body[1] if isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str) else body[0]
        indent = " " * first.col_offset
        injection = (
            f"{indent}from runtime_publication_guard import preflight as _source_preflight\n"
            f"{indent}_source_decision = _source_preflight(project_id, {loader_expression}, workspace_root={workspace}, operation={operation})\n"
            f"{indent}if _source_decision is not None:\n{indent}    return _source_decision\n"
        )
        insertions.append((first.lineno - 1, injection))
        names.append(node.name)
    for line, injection in sorted(insertions, reverse=True):
        lines.insert(line, injection)
    patched = "".join(lines)
    compile(patched, "independent-overlay", "exec")
    return patched, names
