from __future__ import annotations

import importlib


def main() -> None:
    module = importlib.import_module("project_explicit_operations")
    assert hasattr(module, "router"), "router_missing"

    paths = {route.path for route in module.router.routes}
    expected = {
        "/projects/file/read-safe",
        "/projects/file/patch-text",
        "/projects/compose/explicit",
    }
    missing = expected - paths
    assert not missing, f"missing_routes={sorted(missing)}"

    assert module.ProjectPatchTextRequest(project_id="x", path="README.md", old="a", new="b").confirm == ""
    assert module.ProjectComposeExplicitRequest(project_id="x", compose_file="docker-compose.yml").action == "status"

    print("PROJECT_EXPLICIT_IMPORT=OK")
    print("PROJECT_EXPLICIT_ROUTER=OK")
    for path in sorted(expected):
        print(f"ROUTE={path}")


if __name__ == "__main__":
    main()
