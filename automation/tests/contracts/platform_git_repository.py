"""Contratos offline de transporte Git, persistencia y fuente privada."""
import importlib.util
from pathlib import Path
import os
import subprocess
import tempfile
import threading
import unittest
from urllib.request import Request, urlopen
from urllib.error import HTTPError
from http.server import ThreadingHTTPServer

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT/'automation/common/roles/platform_git_repository'


def load(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROLE/'files'/filename)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


R = load('repository', 'repository.py')
H = load('git_server', 'git-server.py')


class Repository(unittest.TestCase):
    def setUp(self):
        from unittest.mock import patch
        p = patch.dict(os.environ, {'KUBECONFIG': '/private/example/kubeconfig'})
        p.start()
        self.addCleanup(p.stop)

    def test_bundle_source_and_backup_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source'
            source.mkdir()
            (source/'resource.yml').write_text('apiVersion: v1\nkind: ConfigMap\nmetadata: {name: smoke}\n')
            bundle = root/'platform.bundle'
            R.create_bundle(source, bundle)
            self.assertEqual(R.validate_bundle(bundle), bundle.resolve())
            self.assertEqual(bundle.stat().st_mode & 0o777, 0o600)
            (source/'secret.yml').write_text('kind: Secret\ndata: {password: abc}\n')
            with self.assertRaises(ValueError):
                R.create_bundle(source, root/'bad.bundle')
            (source/'secret.yml').unlink()
            (source/'password.txt').write_text('password=real-value')
            with self.assertRaises(ValueError):
                R.validate_tree(source)
            (source/'password.txt').unlink()
            (source/'outside').symlink_to('/etc/hosts')
            with self.assertRaises(ValueError):
                R.validate_tree(source)
            with self.assertRaises(ValueError):
                R.outside_git(ROOT/'private.bundle')

    def test_git_reads_work_but_remote_writes_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source'
            source.mkdir()
            (source/'resource.yml').write_text('kind: ConfigMap\n')
            bundle = root/'source.bundle'
            R.create_bundle(source, bundle)
            R.run(['git', 'clone', '-b', 'main', '--bare', str(bundle), str(root/'platform.git')])
            R.run(['git', '-C', str(root/'platform.git'), 'config', 'http.receivepack', 'false'])
            old = os.environ.get('GIT_RAIZ')
            os.environ['GIT_RAIZ'] = tmp
            server = ThreadingHTTPServer(('127.0.0.1', 0), H.GitReadOnly)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            url = f'http://127.0.0.1:{server.server_port}/platform.git'
            try:
                R.run(['git', 'clone', '-q', url, str(root/'clone')])
                self.assertTrue((root/'clone/resource.yml').exists())
                for path, data in [('/info/refs?service=git-receive-pack', None),
                                   ('/git-receive-pack', b'data'), ('/arbitrary', b'data')]:
                    with self.assertRaises(HTTPError) as context:
                        urlopen(Request(url+path, data=data))
                    self.assertEqual(context.exception.code, 403)
                    context.exception.close()
                result = subprocess.run(['git', '-C', str(root/'clone'), 'push', 'origin', 'main'],
                                        capture_output=True)
                self.assertNotEqual(result.returncode, 0)
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                if old is None:
                    os.environ.pop('GIT_RAIZ', None)
                else:
                    os.environ['GIT_RAIZ'] = old

    def test_private_backup_and_restore_transport(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root/'source'
            source.mkdir()
            (source/'resource.yml').write_text('kind: ConfigMap\n')
            bundle = root/'platform.bundle'
            R.create_bundle(source, bundle)
            backup = root/'backup.bundle'
            with patch.object(R, 'run', side_effect=[b'https://expected.invalid', bundle.read_bytes()]) as command:
                R.transfer('backup', backup, 'cl-platform-gitops', 'git-pod', 'https://expected.invalid')
                args = command.call_args.args[0]
                self.assertEqual(args[:5], ['oc', '-n', 'cl-platform-gitops', 'exec', 'git-pod'])
                self.assertIn('bundle create', args[-1])
            self.assertEqual(backup.read_bytes(), bundle.read_bytes())
            self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
            with patch.object(R, 'run', return_value=b'https://expected.invalid'), self.assertRaises(ValueError):
                R.transfer('backup', backup, 'cl-platform-gitops', 'git-pod', 'https://expected.invalid')
            with patch.object(R, 'validate_bundle', return_value=backup), patch.object(R, 'run', side_effect=[b'https://expected.invalid', b'']) as command:
                R.transfer('restaurar', backup, 'cl-platform-gitops', 'git-pod', 'https://expected.invalid')
                args = command.call_args.args[0]
                self.assertIn('update-ref refs/heads/main $sha', args[-1])
                self.assertNotIn('receivepack true', args[-1])
                self.assertIn('stdin', command.call_args.kwargs)

    def test_context_and_secret_json_generator_guards(self):
        from unittest.mock import patch
        with patch.object(R, 'run', return_value=b'https://other.invalid') as command:
            with self.assertRaises(ValueError):
                R.transfer('publicar', '/private/example.bundle', 'ns', 'pod', 'https://expected.invalid')
            self.assertEqual(command.call_count, 1)  # Ningún exec antes de comparar API.
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name, text in [('secret.json', '{"kind":"Secret","data":{}}'),
                               ('kustomization.yaml', 'secretGenerator: [{name: db}]'),
                               ('kustomization.yaml', 'generators: [plugin.yaml]'),
                               ('unknown.bin', 'opaque payload')]:
                path = root/name
                path.write_text(text)
                with self.assertRaises(ValueError):
                    R.validate_tree(root)
                path.unlink()

    def test_two_releases_survive_backup_restore(self):
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            live = root/'live'
            live.mkdir()
            R.run(['git', 'init', '-q', '--bare', '-b', 'main', str(live/'platform.git')])
            source = root/'source'
            source.mkdir()
            original_run = R.run
            def local_exec(args, **kwargs):
                if args[:3] == ['oc', 'config', 'view']:
                    return b'https://expected.invalid'
                if args[0] == 'oc':
                    script = args[-1].replace('/srv/git', str(live))
                    return original_run(['bash', '-ceu', script], **kwargs)
                return original_run(args, **kwargs)
            shas = []
            with patch.object(R, 'run', side_effect=local_exec):
                for index in range(2):
                    (source/'resource.yml').write_text(f'kind: ConfigMap\nmetadata: {{name: version-{index}}}\n')
                    bundle = root/f'version-{index}.bundle'
                    R.create_bundle(source, bundle)
                    R.transfer('publicar', bundle, 'ns', 'pod', 'https://expected.invalid')
                    shas.append(original_run(['git', '-C', str(live/'platform.git'), 'rev-parse', 'main']).decode().strip())
                backup = root/'backup.bundle'
                R.transfer('backup', backup, 'ns', 'pod', 'https://expected.invalid')
                # Simular pérdida del PVC; restaurar un repositorio bare nuevo.
                import shutil
                shutil.rmtree(live/'platform.git')
                original_run(['git', 'init', '-q', '--bare', '-b', 'main', str(live/'platform.git')])
                R.transfer('restaurar', backup, 'ns', 'pod', 'https://expected.invalid')
            for sha in shas:
                resolved = original_run(['git', '-C', str(live/'platform.git'), 'rev-parse', 'refs/tags/releases/'+sha]).decode().strip()
                self.assertEqual(resolved, sha)
                self.assertIn(b'kind: ConfigMap', original_run(['git', '-C', str(live/'platform.git'), 'show', sha+':resource.yml']))

    def test_automount_boolean_is_configuration_not_credential(self):
        import json
        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for enabled in (False, True):
                document = {'apiVersion': 'apps/v1', 'kind': 'Deployment',
                            'spec': {'template': {'spec': {
                                'automountServiceAccountToken': enabled}}}}
                for suffix, encode in [('yaml', yaml.safe_dump), ('json', json.dumps)]:
                    path = root/('deployment.'+suffix)
                    path.write_text(encode(document))
                    R.validate_tree(root)
                    path.unlink()
                service_account = {'apiVersion': 'v1', 'kind': 'ServiceAccount',
                                   'automountServiceAccountToken': enabled}
                path = root/'service-account.json'
                path.write_text(json.dumps({'apiVersion': 'v1', 'kind': 'List',
                                            'items': [service_account, document]}))
                R.validate_tree(root)
                path.unlink()
            # No excluir otros campos token, ni valores string del campo booleano.
            for key, value in [('automountServiceAccountToken', True),
                               ('automountServiceAccountToken', False),
                               ('automountServiceAccountToken', 'true'),
                               ('automountServiceAccountToken', 'private-token'),
                               ('bearerToken', 'private-token'), ('token', False),
                               ('clientSecret', 'private-value'), ('api_key', 'private-value'),
                               ('password', 'private-value')]:
                for suffix, encode in [('yaml', yaml.safe_dump), ('json', json.dumps)]:
                    path = root/('resource.'+suffix)
                    path.write_text(encode({'kind': 'ConfigMap', 'data': {key: value}}))
                    with self.assertRaises(ValueError):
                        R.validate_tree(root)
                    path.unlink()
            for value in ['bearerToken=private-token', 'password: private-value',
                          '-----BEGIN PRIVATE KEY-----', '-----BEGIN CERTIFICATE-----']:
                path = root/'resource.yaml'
                path.write_text(yaml.safe_dump({'kind': 'ConfigMap', 'data': {'script': value}}))
                with self.assertRaises(ValueError):
                    R.validate_tree(root)
                path.unlink()

    def test_persistence_and_narrow_network_policy(self):
        from jinja2 import Environment
        import yaml
        defaults = yaml.safe_load((ROLE/'defaults/main.yml').read_text())
        identity = yaml.safe_load((ROOT/'automation/common/platform-argocd.yml').read_text())
        defaults.update(platform_git_repository_argocd_namespace=identity['namespace'],
                        platform_git_repository_repo_server_label=identity['repo_server_label'])
        env = Environment()
        env.filters['to_json'] = __import__('json').dumps
        env.filters['hash'] = lambda *_: 'test-hash'
        text = env.from_string((ROLE/'templates/repository.yml.j2').read_text()).render(
            **defaults, lookup=lambda *_: 'server-source')
        resources = {x['kind']: x for x in yaml.safe_load_all(text)}
        pod = resources['Deployment']['spec']['template']['spec']
        self.assertFalse(pod['automountServiceAccountToken'])
        self.assertNotIn('runAsUser', pod['securityContext'])
        self.assertNotIn('fsGroup', pod['securityContext'])  # SCC asigna el grupo válido.
        self.assertTrue(any('persistentVolumeClaim' in x for x in pod['volumes']))
        self.assertFalse(any('emptyDir' in x for x in pod['volumes']))
        peer = resources['NetworkPolicy']['spec']['ingress'][0]['from'][0]
        self.assertEqual(peer['namespaceSelector']['matchLabels']['kubernetes.io/metadata.name'], identity['namespace'])
        self.assertEqual(peer['podSelector']['matchLabels']['app.kubernetes.io/name'], identity['repo_server_label'])
        self.assertIn('http.receivepack false', pod['containers'][0]['args'][0])
        self.assertEqual(defaults['platform_git_repository_operation'], 'verificar')

    def test_canonical_controller_identity_and_read_only_verification(self):
        import copy
        import yaml
        from common_roles import run_tasks
        tasks = yaml.safe_load((ROLE/'tasks/main.yml').read_text())
        identity = yaml.safe_load((ROOT/'automation/common/platform-argocd.yml').read_text())
        defaults = yaml.safe_load((ROLE/'defaults/main.yml').read_text())
        canonical_probe = dict(defaults, role_path=str(ROLE))
        self.assertEqual(run_tasks([tasks[0]], canonical_probe).returncode, 0)
        values = dict(platform_git_repository_operation='verificar',
                      platform_git_repository_argocd_identity=identity,
                      platform_git_repository_argocd_namespace=identity['namespace'],
                      platform_git_repository_repo_server_label=identity['repo_server_label'])
        self.assertEqual(run_tasks([tasks[0]], values).returncode, 0)
        for variable in ['platform_git_repository_argocd_namespace', 'platform_git_repository_repo_server_label']:
            invalid = dict(values, **{variable: 'foreign-controller'})
            self.assertNotEqual(run_tasks([tasks[0]], invalid).returncode, 0)
        installer = tasks[1]
        self.assertEqual(installer['ansible.builtin.include_role']['tasks_from'], 'asegurar_recurso')
        self.assertEqual(installer['vars']['recurso_actualizar_gestionado'], "{{ platform_git_repository_resource.kind == 'NetworkPolicy' }}")
        install_probe = copy.deepcopy(installer)
        for key in ['ansible.builtin.include_role', 'vars', 'loop', 'loop_control']:
            install_probe.pop(key)
        install_probe['ansible.builtin.fail'] = {'msg': 'VERIFICATION_MUST_NOT_WRITE'}
        self.assertEqual(run_tasks([install_probe], values).returncode, 0)
        self.assertNotEqual(run_tasks([install_probe], dict(values, platform_git_repository_operation='instalar')).returncode, 0)
        lab_defaults = yaml.safe_load((ROOT/'automation/labs/lab06/roles/lab06/defaults/main.yml').read_text())
        self.assertNotEqual(lab_defaults['lab06_argocd_namespace'], identity['namespace'])

    def test_network_policy_guard_rejects_wrong_namespace_or_label(self):
        import copy
        import yaml
        from common_roles import run_tasks
        tasks = yaml.safe_load((ROLE/'tasks/main.yml').read_text())
        assertion = next(t for t in tasks if t['name'] == 'Verificar PVC enlazado y política restringida al repo-server')
        identity = yaml.safe_load((ROOT/'automation/common/platform-argocd.yml').read_text())
        peer = {'namespaceSelector': {'matchLabels': {'kubernetes.io/metadata.name': identity['namespace']}},
                'podSelector': {'matchLabels': {'app.kubernetes.io/name': identity['repo_server_label']}}}
        controls = {'results': [{'resources': [{'status': {'phase': 'Bound'}}]},
                               {'resources': [{'spec': {'ingress': [{'from': [peer]}]}}]}]}
        values = dict(platform_git_repository_controls=controls,
                      platform_git_repository_argocd_namespace=identity['namespace'],
                      platform_git_repository_repo_server_label=identity['repo_server_label'])
        self.assertEqual(run_tasks([assertion], values).returncode, 0)
        for selector, key in [('namespaceSelector', 'kubernetes.io/metadata.name'), ('podSelector', 'app.kubernetes.io/name')]:
            invalid = copy.deepcopy(values)
            invalid['platform_git_repository_controls']['results'][1]['resources'][0]['spec']['ingress'][0]['from'][0][selector]['matchLabels'][key] = 'foreign-controller'
            self.assertNotEqual(run_tasks([assertion], invalid).returncode, 0)


if __name__ == '__main__':
    unittest.main()
