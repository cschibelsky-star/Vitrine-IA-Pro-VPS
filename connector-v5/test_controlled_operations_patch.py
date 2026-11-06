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

def test_avello_policy_allowlist_isolated():
    # Inspect the literal policy in the versioned patch without applying
    # legacy migration steps that require a historical main.py baseline.
    source = Path(__file__).with_name("controlled_operations_patch.py").read_text(encoding="utf-8")
    marker = 'CONTROLLED_COMPOSE_POLICY: dict[str, dict[str, Any]] = {'
    assert source.count(marker) == 1
    block_start = source.index('    "vitrine-avello-private": {', source.index(marker))
    block_end = source.index('    },', block_start) + len('    },')
    avello = source[block_start:block_end]
    assert '"compose_files": {"integrations/avello-private-mcp/compose.hml.yml"}' in avello
    assert '"services": {"avello_private_mcp"}' in avello
    assert '"run_once": set()' in avello
    assert '"build": {"avello_private_mcp"}' in avello
    assert '"up": {"avello_private_mcp"}' in avello
    assert 'broad_compose_mutation_disabled' in source
