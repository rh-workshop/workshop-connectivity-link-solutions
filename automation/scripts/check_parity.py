"""Compara fixtures ADoc/Jinja sin ejecutar Bash, Ansible ni I/O de clúster."""
import argparse
from pathlib import Path
import re
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_render import environment, resolve
from workshop_pages import SKIP, workshop_root
import yaml

AUTOMATION = Path(__file__).resolve().parents[1]
ROOT = workshop_root()


def identity(resource):
    meta = resource.get('metadata', {})
    return (resource.get('apiVersion'), resource.get('kind'), meta.get('namespace'), meta.get('name'))


def differences(left, right, path='$'):
    """Conserva tipos, todos los campos y orden de listas; ignora solo formato YAML."""
    if type(left) is not type(right):
        return [f'{path}: tipos distintos {type(left).__name__}/{type(right).__name__}']
    if isinstance(left, dict):
        output = []
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                output.append(f'{path}.{key}: campo ausente en una fuente')
            else:
                output.extend(differences(left[key], right[key], f'{path}.{key}'))
        return output
    if isinstance(left, list):
        output = [] if len(left) == len(right) else [f'{path}: longitud distinta']
        for index, (a, b) in enumerate(zip(left, right)):
            output.extend(differences(a, b, f'{path}[{index}]'))
        return output
    return [] if left == right else [f'{path}: valor distinto {left!r}/{right!r}']


def coverage(fixtures, exclusion_path):
    covered = {entry if isinstance(entry, str) else entry['path']
               for path in fixtures for entry in yaml.safe_load(path.read_text())['templates']}
    all_templates = {path.relative_to(AUTOMATION).as_posix()
                     for path in (AUTOMATION / 'labs').glob('*/roles/*/templates/*.j2')}
    entries = yaml.safe_load(exclusion_path.read_text())['templates']
    excluded = {entry['path'] for entry in entries}
    if (len(entries) != len(excluded) or covered & excluded or
            covered | excluded != all_templates or
            any(entry.get('status') != 'not_compared' or not entry.get('reason', '').strip() for entry in entries)):
        raise ValueError('Cobertura incompleta, duplicada o exclusión sin motivo; actualizar clasificación explícita')
    return len(covered), len(all_templates), len(excluded)


def check(fixture_path, render_dir=None):
    fixture = yaml.safe_load(fixture_path.read_text())
    if not fixture.get('templates'):
        raise ValueError('Fixture sin plantillas: no hay cobertura comprobable')
    source = (ROOT / fixture['source_page']).read_text()
    blocks = re.findall(r'\[source,bash[^\]]*\]\n----\n(.*?)\n----', source, re.S)
    heredoc_command = r'(?:oc apply -f -|cat > [^\n]+?)' if fixture.get('include_file_heredocs') else r'oc apply -f -'
    bodies = [item for block in blocks for item in
              re.findall(heredoc_command + r" <<('EOF'|EOF)\n(.*?)\nEOF(?:\n|$)", block, re.S)]
    indices = fixture.get('heredoc_indices', list(range(len(bodies))))
    if not indices or len(set(indices)) != len(indices) or any(type(i) is not int or i < 0 or i >= len(bodies) for i in indices):
        raise ValueError('Selección de heredocs vacía, duplicada o fuera de rango')
    manifests = []
    for index in indices:
        delimiter, block = bodies[index]
        # Solo heredocs oc apply, no sustituciones de comandos ni expansión Bash.
        for body in [block]:
            def substitute(match):
                key = match.group(1)
                if key not in fixture['shell']:
                    raise ValueError(f'Variable sin fixture: {key}')
                return str(fixture['shell'][key])
            expanded = body if delimiter == "'EOF'" else re.sub(r'\$\{([A-Z_][A-Z_0-9]*)\}', substitute, body)
            # Bash retira el escape de dólar en heredocs sin comillas; nunca ejecutarlo.
            if delimiter == 'EOF':
                expanded = expanded.replace('\\$', '$')
            if delimiter == 'EOF' and ('${' in expanded or '$(' in expanded):
                raise ValueError('Expansión Bash no soportada: ampliar fixture, no ejecutar shell')
            manifests.extend((index, resource) for resource in yaml.safe_load_all(expanded) if resource is not None)
    render_fixture = None
    if fixture.get('render_fixture'):
        render_fixture = yaml.safe_load((AUTOMATION / fixture['render_fixture']).read_text())
    errors = []
    count = 0
    for entry in fixture['templates']:
        template_path = entry if isinstance(entry, str) else entry['path']
        selected = indices if isinstance(entry, str) else entry.get('heredoc_indices', indices)
        if not selected or any(i not in indices for i in selected):
            raise ValueError(f'{template_path}: selección de heredocs no cubierta por la fixture')
        template = AUTOMATION / template_path
        role = template.parent.parent
        variables = {}
        if render_fixture:
            variables.update(yaml.safe_load((role / 'defaults/main.yml').read_text()) or {})
            variables.update(render_fixture['shared'])
            variables.update(render_fixture['roles'].get(role.name, {}))
        variables.update(fixture.get('jinja', {}))
        if isinstance(entry, dict):
            variables.update(entry.get('jinja', {}))
        env = environment(role)
        rendered = env.from_string(template.read_text()).render(**resolve(variables, env))
        resources = list(yaml.safe_load_all(rendered))
        if render_dir:
            render_dir.mkdir(parents=True, exist_ok=True)
            (render_dir / template.name.removesuffix('.j2')).write_text(rendered)
        for resource in resources:
            matches = [item for index, item in manifests if index in selected and identity(item) == identity(resource)]
            if len(matches) != 1:
                errors.append(f'{template_path}: {len(matches)} heredocs con identidad {identity(resource)}')
                continue
            errors.extend(f'{template_path}: {item}' for item in differences(matches[0], resource))
            count += 1
    if errors:
        print('\n'.join(f'FAIL paridad: {item}' for item in errors), file=sys.stderr)
        return 1
    print(f'PASS paridad: {count} recursos ({fixture_path.name}); solo escenarios explícitos')
    return 0


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--fixture', type=Path, default=None)
    parser.add_argument('--render-dir', type=Path)
    args = parser.parse_args()
    if ROOT is None:
        print(f'SKIP paridad: {SKIP}')
        sys.exit(0)
    try:
        fixtures = [args.fixture] if args.fixture else sorted((AUTOMATION / 'tests/fixtures').glob('parity-*.yml'))
        result = max(check(path, args.render_dir / path.stem if args.render_dir else None) for path in fixtures)
        if not args.fixture:
            covered, total, excluded = coverage(fixtures, AUTOMATION / 'tests/fixtures/content-parity-exclusions.yml')
            print(f'Cobertura explícita: {covered} de {total} plantillas; '
                  f'{excluded} no comparadas con motivo, más variantes no seleccionadas')
        sys.exit(result)
    except (ValueError, OSError, yaml.YAMLError) as error:
        print(f'FAIL paridad: {error}', file=sys.stderr)
        sys.exit(1)
