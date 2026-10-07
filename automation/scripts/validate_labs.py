"""Planifica o ejecuta wrappers Ansible existentes; resultados privados y sin secretos."""
import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

import yaml

AUTOMATION = Path(__file__).resolve().parents[1]
ROOT = AUTOMATION.parent


def inside(path, root=ROOT):
    return path.resolve().is_relative_to(root.resolve())


def in_git(path):
    path = path.resolve()
    return inside(path) or any((parent / '.git').exists() for parent in [path, *path.parents])


def load_catalog():
    from check_catalog import check
    check()
    return {entry['id']: entry for entry in yaml.safe_load((AUTOMATION / 'catalog.yml').read_text())['labs']}


def plan(catalog, requested):
    selected = []
    for lab in requested:
        if lab not in catalog:
            raise ValueError(f'Laboratorio desconocido: {lab}')
        lab = catalog[lab].get('alias_of', lab)
        if lab not in selected:
            selected.append(lab)
    role_ids = {Path(entry['role']).name: lab for lab, entry in catalog.items() if entry.get('role')}
    ordered, visiting = [], set()
    def visit(lab):
        if lab in visiting:
            raise ValueError('Ciclo de dependencias del catálogo')
        if lab in ordered:
            return
        visiting.add(lab)
        for role in catalog[lab].get('dependencies', []):
            dependency = role_ids.get(role)
            if dependency in selected:
                visit(dependency)
        for dependency in catalog[lab].get('external_dependencies', []):
            if dependency in selected:
                visit(dependency)
        visiting.remove(lab)
        ordered.append(lab)
    for lab in selected:
        visit(lab)
    return [catalog[lab] for lab in ordered]


def values_file(path):
    path = path.expanduser().resolve()
    if in_git(path) or not path.is_file() or path.stat().st_mode & 0o077:
        raise ValueError('--values debe ser un archivo privado (0600) fuera del repositorio')
    values = yaml.safe_load(path.read_text())
    if not isinstance(values, dict):
        raise ValueError('--values requiere un objeto YAML')
    # No aceptar expresiones ni truthy strings que puedan activar demos globales.
    if values.get('lab12_demos', False) is not False:
        raise ValueError('lab12_demos globales están prohibidas en este runner')
    if not isinstance(values.get('lab_id'), str) or not re.fullmatch(r'[a-z0-9][a-z0-9-]*', values['lab_id']):
        raise ValueError('--values requiere lab_id simple, en minúsculas')
    if not isinstance(values.get('openshift_api_esperada'), str) or not values['openshift_api_esperada'].startswith('https://'):
        raise ValueError('--values requiere openshift_api_esperada explícita')
    return path, values


def private_output(path=None):
    if path is None:
        base = Path.home() / '.local/state/workshop-connectivity-link/validation'
        base.mkdir(parents=True, exist_ok=True, mode=0o700)
        path = Path(tempfile.mkdtemp(prefix='run-', dir=base))
    else:
        path = path.expanduser().resolve()
        if in_git(path):
            raise ValueError('--output-dir debe quedar fuera del repositorio')
        # Un directorio nuevo evita sobrescribir evidencia previa o seguir symlinks.
        path.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(path, 0o700)
    return path


def command(entry, values):
    role = Path(entry['role']).name
    overrides = {f'{role}_validar': True, 'lab12_demos': False}
    return ['ansible-playbook', str(Path(entry['playbook']).relative_to('ansible')),
            '--extra-vars', '@' + str(values), '--extra-vars', json.dumps(overrides)]


def run(entries, output, values_path=None, values=None, execute=False, invoke=subprocess.run):
    values = values or {}
    if execute and values.get('lab12_demos', False) is not False:
        raise ValueError('lab12_demos globales están prohibidas en este runner')
    results = []
    failed = False
    for entry in entries:
        lab = entry['id']
        row = {'lab': lab, 'source_page': entry['source_page'],
               'prerequisite_roles': entry.get('dependencies', []),
               'external_prerequisites': entry.get('external_dependencies', []),
               'operation': 'inspection' if lab in ('lab01', 'lab02') else 'run_and_validate',
               'status': 'skipped', 'exit_code': None}
        if not entry.get('playbook'):
            row.update(status='manual', operation='manual', reason='Sin wrapper; seguir la página')
        elif failed:
            row['reason'] = 'No ejecutado tras un fallo anterior'
        elif not execute:
            row['reason'] = 'Plan; falta --execute'
        elif lab == 'lab07' and values.get('entrada_modo') == 'route':
            row['reason'] = 'Lab7 requiere LoadBalancer; modo route omite el rol'
        else:
            log = output / f'{lab}.log'
            row['log'] = log.name
            # O_EXCL y modo0600 desde creación, no chmod tardío después de escribir.
            fd = os.open(log, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            try:
                with os.fdopen(fd, 'w') as stream:
                    completed = invoke(command(entry, values_path), cwd=AUTOMATION / 'ansible',
                                       stdout=stream, stderr=subprocess.STDOUT, check=False)
                row['exit_code'] = completed.returncode
                row['status'] = 'passed' if completed.returncode == 0 else 'failed'
                row['reason'] = 'Resultado del proceso Ansible; no certifica todas las ramas ni códigos HTTP'
                failed = completed.returncode != 0
            except (OSError, KeyboardInterrupt):
                # No serializar excepciones que puedan contener rutas/argumentos privados.
                row.update(status='failed', reason='No fue posible iniciar Ansible')
                failed = True
        results.append(row)
    report = {'created_utc': datetime.now(timezone.utc).isoformat(), 'executed': execute,
              'scope': 'Exit codes de wrappers; logs privados, no informe HTTP', 'results': results}
    fd = os.open(output / 'report.json', os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(report, stream, indent=2, ensure_ascii=False)
        stream.write('\n')
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--list', action='store_true')
    parser.add_argument('--labs', help='IDs separados por coma; lab04 es alias de lab04a')
    parser.add_argument('--values', type=Path, help='Archivo YAML privado externo, nunca impreso')
    parser.add_argument('--output-dir', type=Path, help='Directorio nuevo fuera del repositorio')
    parser.add_argument('--execute', action='store_true', help='Ejecuta y modifica recursos según wrappers')
    args = parser.parse_args()
    catalog = load_catalog()
    if args.list:
        print('\n'.join(catalog))
        return 0
    if not args.labs:
        parser.error('Indica --labs o --list')
    entries = plan(catalog, [lab.strip() for lab in args.labs.split(',')])
    values_path, values = (None, {}) if args.values is None else values_file(args.values)
    if args.execute and values_path is None:
        raise ValueError('--execute requiere --values privado')
    # Para declarar Lab7 skipped con precisión hay que conocer la rama efectiva.
    if args.execute and any(e['id'] == 'lab07' for e in entries) and values.get('entrada_modo') not in ('route', 'loadbalancer'):
        raise ValueError('Lab7 requiere entrada_modo explícito: route o loadbalancer')
    output = private_output(args.output_dir)
    report = run(entries, output, values_path, values, args.execute)
    for row in report['results']:
        print(f"{row['lab']}: {row['status']}")
    print(f'Reporte privado: {output / "report.json"}')
    return int(any(row['status'] == 'failed' for row in report['results']))


if __name__ == '__main__':
    try:
        sys.exit(main())
    except ValueError as error:
        print(f'FAIL runner: {error}', file=sys.stderr)
        sys.exit(2)
    except (OSError, yaml.YAMLError):
        # Errores de YAML pueden incluir la línea de un secreto: no volcarlos.
        print('FAIL runner: revisa IDs, valores privados, destino y directorio de salida; consulta --help', file=sys.stderr)
        sys.exit(2)
