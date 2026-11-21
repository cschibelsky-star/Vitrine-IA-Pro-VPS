import json
from pathlib import Path


def test_cockpit_manifest_declares_homologation_only_by_default():
    path = Path('project-manager/manifests/cockpit-escritorio-hml.json')
    manifest = json.loads(path.read_text(encoding='utf-8'))
    assert manifest['id'] == 'cockpit-escritorio-hml'
    assert manifest['repository']['url'].endswith('vitrine-ai-pro.git')
    assert manifest['docker']['compose_file'] == 'docker-compose.cockpit-hml.yml'
    assert manifest['deployment']['homologation']['automatic'] is True
    assert manifest['deployment']['production']['automatic'] is False
    assert manifest['deployment']['production']['requires_explicit_cutover'] is True


if __name__ == '__main__':
    test_cockpit_manifest_declares_homologation_only_by_default()
    print('cockpit manifest contract: OK')
