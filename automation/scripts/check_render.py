"""Render offline de TODAS las plantillas lab y contrato estructural YAML básico.

No prueba schemas CRD ni admisión del API. Nunca lee inventory/kubeconfig/env.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys

from jinja2 import Environment, StrictUndefined
import yaml

sys.path.insert(0,str(Path(__file__).resolve().parent))
from platform_identity import SOURCE as IDENTITY_SOURCE, load_identity

AUTOMATION = Path(__file__).resolve().parents[1]


def validate(resource, label):
    if not isinstance(resource, dict):
        raise ValueError(f'{label}: documento no es objeto')
    for field in ('apiVersion', 'kind'):
        if not isinstance(resource.get(field), str) or not resource[field]:
            raise ValueError(f'{label}: {field} ausente o inválido')
    metadata = resource.get('metadata')
    if not isinstance(metadata, dict) or not isinstance(metadata.get('name'), str) or not metadata['name']:
        raise ValueError(f'{label}: metadata.name ausente o inválido')
    if 'namespace' in metadata and not isinstance(metadata['namespace'], str):
        raise ValueError(f'{label}: namespace no es texto')
    for key in ('labels', 'annotations'):
        if key in metadata and (not isinstance(metadata[key], dict) or
                any(not isinstance(v, str) for v in metadata[key].values())):
            raise ValueError(f'{label}: {key} debe contener valores de texto')
    if 'spec' in resource and not isinstance(resource['spec'], dict):
        raise ValueError(f'{label}: spec no es objeto')


def environment(role):
    env = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
    # Subconjunto explícito usado por estas plantillas; nunca ejecutar otros lookups.
    def lookup(plugin, name):
        if plugin in {'file','ansible.builtin.file'} and isinstance(name,str) and Path(name).resolve() == IDENTITY_SOURCE.resolve():
            load_identity()  # Validar el único archivo canónico, nunca aceptar otro lookup.
            return IDENTITY_SOURCE.read_text().rstrip('\n')
        if plugin == 'ansible.builtin.file':
            if name in ('git-servidor.py', 'git-lab.sh') and role.name == 'lab06':
                return (role / 'files' / name).read_text().rstrip('\n')
            shared_http = AUTOMATION / 'common/roles/comun/files/http-echo-server.py'
            if role.name in ('lab10', 'lab11') and Path(name).resolve() == shared_http.resolve():
                return shared_http.read_text().rstrip('\n')
        raise ValueError(f'Lookup no autorizado para fixture: {plugin}/{name}')
    env.globals['lookup'] = lookup
    env.globals['role_path'] = str(role)
    env.globals['wk_platform_argocd'] = load_identity()
    env.filters['from_yaml'] = yaml.safe_load
    env.filters['hash'] = lambda value, algorithm: hashlib.new(algorithm, value.encode()).hexdigest()
    env.filters['to_json'] = json.dumps
    return env


def resolve(variables, env, passes=5):
    """Resuelve variables que contienen Jinja (p. ej. "x-{{ lab_id }}"), como hace Ansible al usarlas."""
    for _ in range(passes):
        changed = False
        for key, value in list(variables.items()):
            if isinstance(value, str) and '{{' in value:
                try:
                    rendered = env.from_string(value).render(**variables)
                except Exception:
                    continue
                if rendered != value:
                    variables[key], changed = rendered, True
        if not changed:
            break
    return variables


def check(fixture_path, render_dir=None):
    fixture = yaml.safe_load(fixture_path.read_text())
    templates = sorted((AUTOMATION / 'labs').glob('*/roles/*/templates/*.j2'))
    if not templates:
        raise ValueError('No se encontraron plantillas')
    resources, renders = 0, 0
    errors = []
    for template in templates:
        role = template.parent.parent
        variables = yaml.safe_load((role / 'defaults/main.yml').read_text()) or {}
        variables.update(fixture['shared'])
        variables.update(fixture['roles'].get(role.name, {}))
        relative = template.relative_to(AUTOMATION).as_posix()
        scenarios = [{}] + fixture.get('variants', {}).get(relative, [])
        for number, scenario in enumerate(scenarios):
            label = f'{relative} [{number}]'
            try:
                env = environment(role)
                rendered = env.from_string(template.read_text()).render(**resolve(variables | scenario, env))
                documents = [r for r in yaml.safe_load_all(rendered) if r is not None]
                if not documents:
                    raise ValueError('Plantilla sin recursos')
                for document in documents:
                    validate(document, label)
                if render_dir:
                    target = render_dir / relative.removesuffix('.j2')
                    if number:
                        target = target.with_name(f'{target.stem}-variant{number}{target.suffix}')
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(rendered)
                resources += len(documents)
                renders += 1
            except Exception as error:
                errors.append(f'{label}: {error}')
    if errors:
        print('\n'.join(f'FAIL render: {error}' for error in errors), file=sys.stderr)
        return 1
    print(f'PASS render: {len(templates)} plantillas, {renders} escenarios, {resources} recursos; estructura básica, no schema CRD ni paridad universal')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=AUTOMATION / 'tests/fixtures/render-all.yml')
    parser.add_argument('--render-dir', type=Path)
    args = parser.parse_args()
    try:
        sys.exit(check(args.fixture, args.render_dir))
    except (OSError, ValueError, yaml.YAMLError) as error:
        print(f'FAIL render: {error}', file=sys.stderr)
        sys.exit(1)
