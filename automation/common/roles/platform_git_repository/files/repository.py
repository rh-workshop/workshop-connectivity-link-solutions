"""Bundle privado de fuentes declarativas revisadas; publicación/backup mediante RBAC de oc exec.

No sincroniza Applications. La copia fuera del clúster es responsabilidad del instructor.
"""
import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile
import yaml


def run(args, **kwargs):
    return subprocess.run(args, check=True, stdout=subprocess.PIPE,
                          stderr=subprocess.PIPE, **kwargs).stdout


def outside_git(path):
    path = Path(path).resolve()
    parent = path if path.is_dir() else path.parent
    if subprocess.run(['git', '-C', str(parent), 'rev-parse', '--show-toplevel'],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
        raise ValueError('La entrada/copia privada debe estar fuera de cualquier checkout Git')
    return path


def validate_tree(root):
    for file in Path(root).rglob('*'):
        if file.is_symlink():
            raise ValueError('No se permiten symlinks en la fuente')
        if not file.is_file() or '.git' in file.relative_to(root).parts:
            continue
        if file.suffix not in ('.yml', '.yaml', '.json'):
            raise ValueError('Sólo se admiten fuentes Kubernetes/Kustomization YAML o JSON')
        text = file.read_text(encoding='utf-8')
        if re.search(r'-----BEGIN (?:[A-Z ]*PRIVATE KEY|CERTIFICATE)-----', text, re.I):
            raise ValueError('Patrón sensible rechazado; revisar también el contenido manualmente')
        def check_credentials(value, path=(), resource_kind=None):
            if not path and isinstance(value, dict):
                resource_kind = value.get('kind')
            if isinstance(value, dict):
                for key, item in value.items():
                    # Campo Kubernetes de configuración, no una credencial. Sólo bool real.
                    pod_spec_paths = {
                        'ServiceAccount': (), 'Pod': ('spec',),
                        **{kind: ('spec', 'template', 'spec') for kind in (
                            'Deployment', 'DaemonSet', 'StatefulSet', 'ReplicaSet',
                            'ReplicationController', 'Job')},
                        'CronJob': ('spec', 'jobTemplate', 'spec', 'template', 'spec'),
                    }
                    if (key == 'automountServiceAccountToken' and isinstance(item, bool)
                            and resource_kind in pod_spec_paths
                            and path == pod_spec_paths[resource_kind]):
                        continue
                    if re.search(r'(?:password|token|client_?secret|api_?key)$', str(key), re.I):
                        if item != '' and not (
                                isinstance(item, str) and item.startswith('${')):
                            raise ValueError('Patrón sensible rechazado; revisar también el contenido manualmente')
                    check_credentials(item, path+(key,), resource_kind)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    if resource_kind == 'List' and path == ('items',):
                        check_credentials(item)
                    else:
                        check_credentials(item, path+(index,), resource_kind)
            elif isinstance(value, str) and re.search(
                    r'(?:password|token|client_?secret|api_?key)\s*[:=]\s*["\']?[^\s"\'${]+',
                    value, re.I):
                raise ValueError('Patrón sensible rechazado; revisar también el contenido manualmente')
        def check(obj):
            if not isinstance(obj, dict):
                raise ValueError('Documento de fuente inválido')
            if obj.get('kind') == 'Secret' or 'secretGenerator' in obj or 'generators' in obj:
                raise ValueError('Secrets y generadores de Secrets/plugins están prohibidos')
            for item in obj.get('items', []):
                check(item)
        for obj in yaml.safe_load_all(text):
            check(obj)
            check_credentials(obj)
            if not obj.get('kind') and file.name.lower() not in ('kustomization.yaml', 'kustomization.yml', 'kustomization.json'):
                raise ValueError('Documento sin kind; los informes no son fuente Git')


def create_bundle(source, output):
    source = outside_git(source)
    output = outside_git(output)
    if (source / ".git").exists():
        raise ValueError("La fuente debe ser una exportación sin metadatos Git")
    validate_tree(source)
    import shutil
    with tempfile.TemporaryDirectory() as tmp:
        tree = Path(tmp)/'source'
        shutil.copytree(source, tree)
        run(['git', 'init', '-q', '-b', 'main', str(tree)])
        run(['git', '-C', str(tree), 'add', '.'])
        run(['git', '-C', str(tree), '-c', 'user.name=Workshop instructor',
             '-c', 'user.email=instructor@example.invalid', 'commit', '-qm', 'Platform source'])
        mask = os.umask(0o077)
        try:
            run(['git', '-C', str(tree), 'bundle', 'create', str(output), 'main'])
        finally:
            os.umask(mask)
    os.chmod(output, 0o600)


def validate_bundle(bundle):
    bundle = outside_git(bundle)
    heads = [line.split() for line in run(['git', 'bundle', 'list-heads', str(bundle)]).decode().splitlines()]
    main = [sha for sha, ref in heads if ref == 'refs/heads/main']
    if len(main) != 1 or any(ref != 'refs/heads/main' and not (
            ref == 'HEAD' and sha == main[0]) and ref != 'refs/tags/releases/'+sha for sha, ref in heads):
        raise ValueError('Bundle sólo admite main y releases fijadas por SHA')
    with tempfile.TemporaryDirectory() as tmp:
        run(['git', 'clone', '-q', '-b', 'main', str(bundle), tmp])
        # Cada versión es una instantánea sin padres; validar también releases de rollback.
        parents = run(['git', '-C', tmp, 'rev-list', '--parents', '--all']).decode().splitlines()
        if any(len(line.split()) != 1 for line in parents):
            raise ValueError('Las versiones deben ser instantáneas sin historia privada')
        for sha in set(sha for sha, _ in heads):
            if run(['git', '-C', tmp, 'rev-parse', sha+'^{commit}']).decode().strip() != sha:
                raise ValueError('Sólo commits directos, sin tags anotados ni mensajes ocultos')
            run(['git', '-C', tmp, 'checkout', '-q', '--detach', sha])
            validate_tree(tmp)

    return bundle


def transfer(operation, bundle, namespace, pod, expected_api):
    if not os.environ.get('KUBECONFIG') or not expected_api:
        raise ValueError('KUBECONFIG explícito y API esperada son obligatorios')
    actual = run(['oc', 'config', 'view', '--minify', '-o', 'jsonpath={.clusters[0].cluster.server}']).decode().strip()
    if actual.rstrip('/') != expected_api.rstrip('/'):
        raise ValueError('El destino oc no coincide con el cliente Ansible; exec cancelado')
    base = ['oc', '-n', namespace, 'exec', pod, '-c', 'git', '-i', '--', 'bash', '-ceu']
    if operation in ('publicar', 'restaurar'):
        path = validate_bundle(bundle)
        # Una instantánea reemplaza main explícitamente; objeto anterior queda para diagnóstico.
        script = ('f=$(mktemp /tmp/platform.XXXXXX); trap \'rm -f "$f"\' EXIT; cat > "$f"; '
                  'old=$(git -C /srv/git/platform.git rev-parse --verify refs/heads/main 2>/dev/null || true); '
                  'if [ -n "$old" ]; then git -C /srv/git/platform.git update-ref refs/tags/releases/$old $old; fi; '
                  'git -C /srv/git/platform.git fetch --tags "$f" refs/heads/main; '
                  'sha=$(git -C /srv/git/platform.git rev-parse FETCH_HEAD); '
                  'git -C /srv/git/platform.git update-ref refs/tags/releases/$sha $sha; '
                  'git -C /srv/git/platform.git update-ref refs/heads/main $sha; '
                  'git -C /srv/git/platform.git config http.receivepack false')
        with path.open('rb') as stream:
            run(base+[script], stdin=stream)
    elif operation == 'backup':
        path = outside_git(bundle)
        if path.exists():
            raise ValueError('No sobrescribir backup existente')
        script = ('f=$(mktemp /tmp/platform.XXXXXX); trap \'rm -f "$f"\' EXIT; '
                  'git -C /srv/git/platform.git bundle create "$f" --all; cat "$f"')
        data = run(base+[script])
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chmod(path, 0o600)


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('operation', choices=['bundle', 'publicar', 'backup', 'restaurar'])
    p.add_argument('--path', required=True)
    p.add_argument('--source')
    p.add_argument('--namespace', default='cl-platform-gitops')
    p.add_argument('--pod')
    p.add_argument('--expected-api')
    args = p.parse_args()
    if args.operation == 'bundle':
        if not args.source:
            p.error('--source requerido')
        create_bundle(args.source, args.path)
    else:
        if not args.pod:
            p.error('--pod requerido')
        transfer(args.operation, args.path, args.namespace, args.pod, args.expected_api)
    print('OK: operación completada; contenido privado no registrado')
