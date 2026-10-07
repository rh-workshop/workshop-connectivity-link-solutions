"""Valida contratos de rutas sin cargar inventarios ni ejecutar Ansible."""
from pathlib import Path
import sys

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workshop_pages import SKIP, workshop_root

AUTOMATION = Path(__file__).resolve().parents[1]
WORKSHOP = workshop_root()


def check():
    catalog = yaml.safe_load((AUTOMATION / 'catalog.yml').read_text())
    assert catalog['schema_version'] == 1, 'Versión de catálogo desconocida'
    entries = catalog['labs']
    ids = [entry['id'] for entry in entries]
    assert len(ids) == len(set(ids)), 'IDs duplicados'
    cleanup = yaml.safe_load((AUTOMATION / 'ansible/playbooks/limpieza.yml').read_text())
    cleanup_tasks = cleanup[0]['tasks']
    for entry in entries:
        lab = entry['id']
        if WORKSHOP:
            assert (WORKSHOP / entry['source_page']).is_file(), f'{lab}: página ausente'
        assert (AUTOMATION / 'labs' / lab / 'README.md').is_file(), f'{lab}: README ausente'
        if 'alias_of' in entry:
            assert entry['alias_of'] in ids and entry['alias_of'] != lab, f'{lab}: alias inválido'
            continue
        assert entry['ownership']['conditions'], f'{lab}: condiciones ausentes'
        for prerequisite in entry.get('external_dependencies', []):
            assert prerequisite in ids and prerequisite != lab, f'{lab}: prerrequisito externo inválido'
        if entry['playbook'] is None:
            assert lab == 'lab00' and entry['role'] is None and entry['cleanup'] is None
            continue
        role = AUTOMATION / entry['role']
        assert role.is_dir(), f'{lab}: rol ausente'
        playbook = yaml.safe_load((AUTOMATION / entry['playbook']).read_text())
        declared = [item['role'] for item in playbook[0]['roles']]
        assert declared == entry['dependencies'] + [role.name], f'{lab}: orden de dependencias distinto al wrapper'
        for dependency in entry['dependencies']:
            candidates = list((AUTOMATION / 'labs').glob(f'*/roles/{dependency}'))
            candidates += list((AUTOMATION / 'common/roles').glob(dependency))
            assert len(candidates) == 1, f'{lab}: dependencia ausente o duplicada {dependency}'
        assert (AUTOMATION / entry['validations']['tasks']).is_file(), f'{lab}: validación ausente'
        clean = entry['cleanup']
        if lab == 'lab00':
            assert clean is None and entry['validations']['execution'] == 'manual'
            continue  # Acceso explícito: rollback CAS separado, no limpieza masiva de User/Identity.
        assert (AUTOMATION / clean['tasks']).is_file(), f'{lab}: limpieza ausente'
        matches = [task for task in cleanup_tasks if clean['tag'] in task.get('tags', [])]
        assert len(matches) == 1, f'{lab}: etiqueta de limpieza ausente o ambigua'
        imported = matches[0]['ansible.builtin.import_role']
        assert imported == {'name': role.name, 'tasks_from': 'limpiar'}, f'{lab}: limpieza no corresponde al rol'
    print(f'PASS catálogo: {len(entries)} entradas; rutas, dependencias ordenadas y limpieza')


if __name__ == '__main__':
    try:
        check()
        if WORKSHOP is None:
            print(f'SKIP páginas del catálogo: {SKIP}')
    except (AssertionError, KeyError, OSError, yaml.YAMLError) as error:
        print(f'FAIL catálogo: {error}', file=sys.stderr)
        sys.exit(1)
