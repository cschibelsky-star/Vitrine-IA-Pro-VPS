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


def test_via_only_isolated_hml_policy_and_no_superconector_permissions():
    from ast import parse, literal_eval, AnnAssign, Name, NodeTransformer, Call, Set

    base = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    source = apply_controlled_operations_patch(apply_marketing_live_patch(base))
    tree = parse(source)
    node = next(
        n for n in tree.body if isinstance(n, AnnAssign)
        and isinstance(n.target, Name) and n.target.id == "CONTROLLED_COMPOSE_POLICY"
    )
    class LiteralSet(NodeTransformer):
        def visit_Call(self, n):
            if isinstance(n.func, Name) and n.func.id == "set" and not n.args and not n.keywords:
                return Set(elts=[])
            raise AssertionError("Unexpected policy call")
    policy = literal_eval(LiteralSet().visit(node.value))
    via = policy["via-integrated-isolated-hml-20261117-ssh"]
    assert via == {
        "compose_files": {"docker-compose.via-isolated-hml.yml"},
        "services": {"via"},
        "run_once": set(),
        "build": {"via"},
        "up": {"via"},
    }
    assert "vitrine-superconector-v2-hml" not in policy
    assert "tvsumare" in policy
    assert policy["tvsumare"]["build"] == set()


def test_via_only_controlled_build_up_and_fail_closed():
    import ast
    from typing import Any
    source = apply_controlled_operations_patch(
        apply_marketing_live_patch(Path(__file__).with_name("main.py").read_text(encoding="utf-8"))
    )
    tree = ast.parse(source)
    policy = next(n for n in tree.body
                  if isinstance(n, ast.AnnAssign)
                  and isinstance(n.target, ast.Name)
                  and n.target.id == "CONTROLLED_COMPOSE_POLICY")
    funcs = [n for n in tree.body if isinstance(n, ast.FunctionDef)
             and n.name in {"_controlled_compose_base", "project_compose_service_execute"}]
    assert len(funcs) == 2
    for f in funcs:
        f.decorator_list = []

    project = "via-integrated-isolated-hml-20261117-ssh"
    compose = "docker-compose.via-isolated-hml.yml"
    root = Path("/srv/projects/via-integrated-isolated-hml-20261117-ssh")
    manifest = {
        "docker": {"project_name": "via-isolated-hml-20261117", "compose_file": compose},
        "runtime": {"allowed_keys": []},
    }
    commands = []
    def safe_file(_project, filename, _strict):
        if filename != compose:
            raise PermissionError("controlled_compose_file_not_allowed")
        return root / "repository" / compose, compose
    def project_paths(_project):
        return manifest, root, root / "repository"
    def runtime_config(_manifest):
        raise PermissionError("runtime_keys_not_configured")
    def fake_run(cmd, cwd, timeout=0):
        commands.append(cmd)
        return {"ok": True, "exit_code": 0}
    env = {
        "Any": Any, "Path": Path,
        "_safe_file": safe_file, "_project_paths": project_paths,
        "_runtime_config": runtime_config, "_run": fake_run,
    }
    module = ast.fix_missing_locations(ast.Module(body=[policy, *funcs], type_ignores=[]))
    exec(compile(module, "<via-hml-policy>", "exec"), env)
    run = env["project_compose_service_execute"]
    for op in ("build", "up"):
        assert run(project, compose, "via", op, "EXECUTAR")["ok"] is True
    assert len(commands) == 2
    assert commands[0][-2:] == ["build", "via"]
    assert commands[1][-5:] == ["up", "-d", "--no-deps", "--no-build", "via"]

    denied = [
        (project, compose, "via", "run_once", "EXECUTAR", "controlled_operation_not_allowed"),
        (project, compose, "database", "build", "EXECUTAR", "controlled_service_not_allowed"),
        ("via", compose, "via", "build", "EXECUTAR", "controlled_service_not_allowed"),
        (project, compose, "via", "up", "", "confirmation_required"),
        (project, "docker-compose.homolog.yml", "via", "build", "EXECUTAR", "controlled_compose_file_not_allowed"),
    ]
    for args in denied:
        result = run(*args[:5])
        assert result["ok"] is False
        assert result["error"] == args[5]
    assert len(commands) == 2

    manifest["docker"]["project_name"] = "repository"
    assert run(project, compose, "via", "build", "EXECUTAR")["error"] == "via_isolated_manifest_mismatch"
    manifest["docker"]["project_name"] = "via-isolated-hml-20261117"
    manifest["runtime"]["allowed_keys"] = ["PRODUCTION_SECRET"]
    assert run(project, compose, "via", "build", "EXECUTAR")["error"] == "via_isolated_manifest_mismatch"
    assert len(commands) == 2
