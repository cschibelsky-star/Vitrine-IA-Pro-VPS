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
        def runtime_config(_manifest):
            raise PermissionError(error)
        env = {
            "Path": Path,
            "CONTROLLED_COMPOSE_POLICY": {
                "vitrine-superconector-v2-hml": {"compose_files": {"superconector-v2/server/docker-compose.hml.yml"}},
                "tvsumare": {"compose_files": {"docker-compose.vps.yml"}},
            },
            "_safe_file": lambda *_: (Path("/tmp/dummy-compose.yml"), "superconector-v2/server/docker-compose.hml.yml"),
            "_project_paths": lambda _: (manifest, Path("/tmp"), Path("/tmp")),
            "_runtime_config": runtime_config,
        }
        exec(code, env)
        return env["_controlled_compose_base"](project_id, "superconector-v2/server/docker-compose.hml.yml")

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
