from pathlib import Path

from marketing_live_patch import apply as apply_marketing_live_patch
from controlled_operations_patch import apply as apply_controlled_operations_patch


def test_recovered_controlled_operations_layer():
    base = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
    source = apply_marketing_live_patch(base)
    source = apply_controlled_operations_patch(source)

    assert 'VERSION = "0.5.13-controlled-operations"' in source
    assert 'CONTROLLED_COMPOSE_POLICY' in source
    assert '"vitrine-ia-pro-core"' in source
    assert '"vitrine-ai-pro-factory"' in source
    assert '"vps-ops-full-catalog-candidate"' in source
    assert '"vps_mcp_snapshot_candidate"' in source
    assert 'broad_compose_mutation_disabled' in source
    assert 'project_compose_service_execute' in source
