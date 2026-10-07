"""Contrato offline de credenciales SSH por repositorio; nunca usa claves reales."""
import base64
from pathlib import Path
import unittest

import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT / 'automation/labs/lab06/roles/lab06'
KEY = '-----BEGIN OPENSSH PRIVATE KEY-----\nFIXTURE-NOT-A-KEY\n-----END OPENSSH PRIVATE KEY-----\n'
URL = 'git@github.com:example/lab06-fixture.git'


class RepositoryCredentials(unittest.TestCase):
    def setUp(self):
        self.tasks = yaml.safe_load((ROLE / 'tasks/repository_credentials.yml').read_text())
        self.env = Environment(undefined=StrictUndefined)
        self.env.filters['b64decode'] = lambda value: base64.b64decode(value).decode()
        self.env.filters['bool'] = bool
        self.variables = dict(lab_id='user7', lab06_git_repo_url=URL,
                              lab06_repository_ssh_private_key=KEY,
                              lab06_repository_credentials_verify_only=True)

    def allowed(self, secret):
        variables = self.variables | {'lab06_repository_secret': {'resources': secret}}
        guard = next(task for task in self.tasks if task['name'].startswith('Rechazar'))
        return all(self.env.compile_expression(rule)(**variables)
                   for rule in guard['ansible.builtin.assert']['that'])

    def secret(self):
        return {'metadata': {'labels': {'workshop.user': 'user7',
                                       'workshop.component': 'lab06-repository',
                                       'argocd.argoproj.io/secret-type': 'repository'}},
                'type': 'Opaque', 'data': {key: base64.b64encode(value.encode()).decode()
                                          for key, value in {'url': URL, 'type': 'git', 'sshPrivateKey': KEY}.items()}}

    def test_secret_exact_repository_and_no_insecure_host_bypass(self):
        import json
        self.env.filters['to_json'] = json.dumps
        rendered = self.env.from_string((ROLE / 'templates/repository-secret.yaml.j2').read_text()).render(
            **self.variables, lab06_repository_credentials_name='lab06-repository-user7',
            lab06_argocd_namespace='openshift-gitops')
        secret = yaml.safe_load(rendered)
        self.assertEqual(secret['stringData'], {'type': 'git', 'url': URL, 'sshPrivateKey': KEY})
        self.assertEqual(secret['metadata']['labels']['argocd.argoproj.io/secret-type'], 'repository')
        self.assertNotIn('insecure', rendered)

    def test_owned_exact_secret_verifies_without_write(self):
        self.assertTrue(self.allowed([self.secret()]))
        writes = [task for task in self.tasks if 'kubernetes.core.k8s' in task]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['when'], [
            'not lab06_repository_credentials_verify_only | bool',
            'lab06_repository_secret.resources | length == 0'])
        self.assertTrue(writes[0]['no_log'])

    def test_foreign_changed_and_duplicate_secrets_rejected(self):
        for mutate in [lambda s: s['metadata']['labels'].update({'workshop.user': 'other'}),
                       lambda s: s['data'].update({'url': base64.b64encode(b'other').decode()}),
                       lambda s: s['data'].update({'sshPrivateKey': base64.b64encode(b'other').decode()}),
                       lambda s: s['data'].update({'password': base64.b64encode(b'other').decode()})]:
            secret = self.secret()
            mutate(secret)
            self.assertFalse(self.allowed([secret]))
        self.assertFalse(self.allowed([self.secret(), self.secret()]))

    def test_absence_requires_explicit_prepare(self):
        self.assertFalse(self.allowed([]))
        self.variables['lab06_repository_credentials_verify_only'] = False
        self.assertTrue(self.allowed([]))

    def test_tag_does_not_select_application_or_bootstrap(self):
        main = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        selected = [task for task in main if 'lab06_repository_credentials' in task.get('tags', [])]
        self.assertEqual(len(selected), 1)
        self.assertEqual(selected[0]['ansible.builtin.import_tasks'], 'repository_credentials.yml')
        for task in self.tasks:
            if task['name'].startswith(('Validar el perfil', 'Leer el Secret', 'Rechazar', 'Crear el Secret')):
                self.assertTrue(task['no_log'])
        defaults = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        self.assertFalse(defaults['lab06_repository_credentials_enabled'])
        self.assertTrue(defaults['lab06_repository_credentials_verify_only'])


if __name__ == '__main__':
    unittest.main()
