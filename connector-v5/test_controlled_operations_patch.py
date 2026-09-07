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
    assert 'broad_compose_mutation_disabled' in source
    assert 'project_compose_service_execute' in source
    assert 'def project_manifest_docker_configure(' in source
    assert 'project_manifest_docker_configure' in source
    assert 'def project_runtime_secret_import_from_container(' in source
    assert '__MIGRATE_EXISTING__' in source