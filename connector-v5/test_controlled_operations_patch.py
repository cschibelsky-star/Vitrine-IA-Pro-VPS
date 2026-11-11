from pathlib import Path

from marketing_live_patch import apply as apply_marketing_live_patch
from controlled_operations_patch import apply as apply_controlled_operations_patch


def test_recovered_controlled_operations_layer():
    base = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    source = apply_marketing_live_patch(base)
    source = apply_controlled_operations_patch(source)

    assert 'VERSION = "0.5.14-runtime-secret-import"' in source
    assert 'CONTROLLED_COMPOSE_POLICY' in source
    assert '"vitrine-ia-pro-core"' in source
    assert '"vitrine-ai-pro-factory"' in source
    assert '"vps-ops-full-catalog-candidate"' in source
    assert '"vps_mcp_snapshot_candidate"' in source
    assert '"v5-0-5-13-recovery-validation"' in source
    assert '"connector_v5_recovery_candidate"' in source
    assert '"tvsumare"' in source
    assert '"docker-compose.vps.yml"' in source
    assert '"web"' in source
    assert '"services": {"web", "web_prod"}' in source
    assert '"up": {"web"}' in source
    assert 'broad_compose_mutation_disabled' in source
    assert 'project_compose_service_execute' in source
    assert 'def project_manifest_docker_configure(' in source
    assert 'project_manifest_docker_configure' in source
    assert 'def project_runtime_secret_import_from_container(' in source
    assert '_project_runtime_secret_set_impl(project_id, key, "__MIGRATE_EXISTING__", confirm)' in source
    assert '("vitrine-ai-social-enterprise", "CENTRO_IA_INTERNAL_TOKEN")' in source
    assert '("vitrine-marketing-agents-core-hml", "CENTRO_IA_INTERNAL_TOKEN")' in source
    assert '("tvsumare-enterprise", "CENTRO_IA_INTERNAL_TOKEN")' in source
    assert '("tvsumare-enterprise", "HEYGEN_API_KEY"): ("tvsumare_web", "HEYGEN_API_KEY")' in source
    assert 'source_value is None or not str(source_value).strip()' in source
    assert '__MIGRATE_EXISTING__' in source

def test_superconector_v2_hml_policy_is_narrow():
    base = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    source = apply_controlled_operations_patch(apply_marketing_live_patch(base))
    assert '"vitrine-superconector-v2-hml": {' in source
    assert '"compose_files": {"superconector-v2/server/docker-compose.hml.yml"}' in source
    assert '"services": {"public_mcp"}' in source
    assert '"build": {"public_mcp"}' in source
    assert '"up": {"public_mcp"}' in source
    assert 'project_id == "vitrine-superconector-v2-hml"' in source
    assert 'manifest.get("runtime", {}).get("allowed_keys") == []' in source
    assert '"run_once": set()' in source


def test_superconector_v2_runtime_exception_is_fail_closed():
    import ast
    import types

    base = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    source = apply_controlled_operations_patch(apply_marketing_live_patch(base))
    module = ast.parse(source)
    target = next(
        node for node in module.body
        if isinstance(node, ast.FunctionDef) and node.name == "_controlled_compose_base"
    )
    target.decorator_list = []
    code = compile(ast.fix_missing_locations(ast.Module(body=[target], type_ignores=[])), "<v5-policy-test>", "exec")

    def run(project_id, keys, error):
        manifest = {"docker": {"project_name": "vitrine-super-v2-public-hml"}, "runtime": {"allowed_keys": keys}}
        compose = "docker-compose.vps.yml" if project_id == "tvsumare" else "superconector-v2/server/docker-compose.hml.yml"
        def runtime_config(_manifest):
            raise PermissionError(error)
        env = {
            "Path": Path,
            "CONTROLLED_COMPOSE_POLICY": {
                "vitrine-superconector-v2-hml": {"compose_files": {"superconector-v2/server/docker-compose.hml.yml"}},
                "tvsumare": {"compose_files": {"docker-compose.vps.yml"}},
            },
            "_safe_file": lambda *_: (Path("/tmp/dummy-compose.yml"), compose),
            "_project_paths": lambda _: (manifest, Path("/tmp"), Path("/tmp")),
            "_runtime_config": runtime_config,
        }
        exec(code, env)
        return env["_controlled_compose_base"](project_id, compose)

    command, relative, directory = run("vitrine-superconector-v2-hml", [], "runtime_keys_not_configured")
    assert command == ["docker", "compose", "-p", "vitrine-super-v2-public-hml", "-f", "/tmp/dummy-compose.yml"]
    assert relative == "superconector-v2/server/docker-compose.hml.yml"

    for project, keys, error in (
        ("tvsumare", [], "runtime_keys_not_configured"),
        ("vitrine-superconector-v2-hml", ["API_KEY"], "runtime_keys_not_configured"),
        ("vitrine-superconector-v2-hml", [], "another_permission_error"),
    ):
        try:
            run(project, keys, error)
        except PermissionError as exc:
            assert str(exc) == error
        else:
            raise AssertionError("runtime exception incorrectly granted")


def test_superconector_v2_controlled_build_authorization_behavior():
    """Exercise actual patched control flow, never invoking real Docker or project code."""
    import ast
    from typing import Any

    source = apply_controlled_operations_patch(
        apply_marketing_live_patch(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
    )
    tree = ast.parse(source)
    policy = next(
        node for node in tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "CONTROLLED_COMPOSE_POLICY"
    )
    helpers = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_controlled_compose_base", "project_compose_service_execute"}
    ]
    assert len(helpers) == 2
    for node in helpers:
        node.decorator_list = []

    calls = []
    hml_path = "superconector-v2/server/docker-compose.hml.yml"
    def resolve_file(_project, requested, _safe):
        assert requested == hml_path
        return Path("/tmp/synthetic-hml-compose.yml"), hml_path

    def resolve_project(_project):
        return (
            {"docker": {"project_name": "vitrine-super-v2-public-hml"},
             "runtime": {"allowed_keys": []}},
            Path("/tmp"), Path("/tmp"),
        )

    def runtime_config(_manifest):
        raise PermissionError("runtime_keys_not_configured")

    def fake_run(cmd, directory, timeout=0):
        calls.append((cmd, directory, timeout))
        return {"ok": True, "exit_code": 0}

    scope = {
        "Any": Any,
        "Path": Path,
        "_safe_file": resolve_file,
        "_project_paths": resolve_project,
        "_runtime_config": runtime_config,
        "_run": fake_run,
    }
    module = ast.fix_missing_locations(ast.Module(body=[policy] + helpers, type_ignores=[]))
    exec(compile(module, "<controlled-policy-behavior>", "exec"), scope)
    execute = scope["project_compose_service_execute"]

    result = execute("vitrine-superconector-v2-hml", hml_path, "public_mcp", "build", "EXECUTAR")
    assert result["ok"] is True
    assert len(calls) == 1
    assert calls[0][0] == [
        "docker", "compose", "-p", "vitrine-super-v2-public-hml",
        "-f", "/tmp/synthetic-hml-compose.yml", "build", "public_mcp",
    ]
    for project, service, operation, confirm, expected in (
        ("tvsumare", "public_mcp", "build", "EXECUTAR", "controlled_service_not_allowed"),
        ("vitrine-superconector-v2-hml", "web_prod", "build", "EXECUTAR", "controlled_service_not_allowed"),
        ("vitrine-superconector-v2-hml", "public_mcp", "run_once", "EXECUTAR", "controlled_operation_not_allowed"),
        ("vitrine-superconector-v2-hml", "public_mcp", "build", "", "confirmation_required"),
    ):
        denial = execute(project, hml_path, service, operation, confirm)
        assert denial["error"] == expected
        assert len(calls) == 1, "Denied request invoked Docker"
