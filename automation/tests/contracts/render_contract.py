"""Comprueba cobertura y rechazo de fixtures incompletas sin usar un clúster."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('render', ROOT / 'automation/scripts/check_render.py')
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)
FIXTURE = ROOT / 'automation/tests/fixtures/render-all.yml'


class RenderContract(unittest.TestCase):
    def run_fixture(self, fixture):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.yml'
            path.write_text(yaml.safe_dump(fixture))
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = RENDER.check(path)
            return result, stdout.getvalue(), stderr.getvalue()

    def test_every_canonical_template_is_rendered(self):
        result, output, _ = self.run_fixture(yaml.safe_load(FIXTURE.read_text()))
        count = len(list((ROOT / 'automation/labs').glob('*/roles/*/templates/*.j2')))
        self.assertEqual(result, 0)
        self.assertIn(f'{count} plantillas', output)

    def test_missing_derived_fact_fails_closed(self):
        fixture = yaml.safe_load(FIXTURE.read_text())
        del fixture['roles']['lab11']['lab11_ca_pem']
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn("'lab11_ca_pem' is undefined", error)

    def test_namespace_type_is_checked(self):
        fixture = yaml.safe_load(FIXTURE.read_text())
        fixture['shared']['wk_ns_gateway'] = 42
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn('namespace no es texto', error)

    def test_identity_lookup_is_exact_and_external_paths_remain_denied(self):
        role=ROOT/'automation/common/roles/platform_git_repository'
        env=RENDER.environment(role)
        actual=yaml.safe_load(env.from_string("{{ lookup('file', role_path ~ '/../../platform-argocd.yml') }}").render())
        self.assertEqual(actual,RENDER.load_identity())
        for file in ['/etc/hosts',str(ROOT/'automation/ansible/inventory/group_vars/all.yml')]:
            with self.assertRaisesRegex(ValueError,'Lookup no autorizado'):
                env.globals['lookup']('file',file)

    def test_external_lookup_is_denied(self):
        env = RENDER.environment(ROOT / 'automation/labs/lab06/roles/lab06')
        with self.assertRaisesRegex(ValueError, 'Lookup no autorizado'):
            env.from_string("{{ lookup('ansible.builtin.env', 'HOME') }}").render()

    def test_lab06_application_read_is_exact_and_namespace_local(self):
        role = ROOT / 'automation/labs/lab06/roles/lab06'
        template = (role / 'templates/application-view.yaml.j2').read_text()
        for lab_id, namespace in [('user41', 'openshift-gitops'), ('user92', 'custom-gitops')]:
            with self.subTest(lab_id=lab_id, namespace=namespace):
                application = 'rhcl-policies-' + lab_id
                objects = list(yaml.safe_load_all(RENDER.environment(role).from_string(template).render(
                    lab_id=lab_id, lab06_argocd_namespace=namespace, lab06_application=application)))
                self.assertEqual([item['kind'] for item in objects], ['Role', 'RoleBinding'])
                name = lab_id + '-application-view'
                for item in objects:
                    self.assertEqual(item['metadata']['namespace'], namespace)
                    self.assertEqual(item['metadata']['name'], name)
                    self.assertEqual(item['metadata']['labels']['workshop.user'], lab_id)
                self.assertEqual(objects[0]['rules'], [{
                    'apiGroups': ['argoproj.io'], 'resources': ['applications'],
                    'resourceNames': [application], 'verbs': ['get']}])
                self.assertEqual(objects[1]['subjects'], [{
                    'kind': 'User', 'name': lab_id, 'apiGroup': 'rbac.authorization.k8s.io'}])
                self.assertEqual(objects[1]['roleRef'], {
                    'kind': 'Role', 'name': name, 'apiGroup': 'rbac.authorization.k8s.io'})

    def test_authorino_log_source_only_allows_get_of_named_deployment(self):
        role = ROOT / 'automation/common/roles/tenant'
        template = (role / 'templates/rbac.yaml.j2').read_text()
        for lab_id in ['user41', 'user92']:
            with self.subTest(lab_id=lab_id):
                documents = list(yaml.safe_load_all(RENDER.environment(role).from_string(template).render(
                    lab_id=lab_id, wk_ns_app='atp-' + lab_id,
                    wk_ns_gateway='gateway-' + lab_id, tenant_ns_cert_manager='cert-manager')))
                name = lab_id + '-authorino-logs-source'
                objects = [item for item in documents if item['metadata']['name'] == name]
                self.assertEqual([item['kind'] for item in objects], ['Role', 'RoleBinding'])
                for item in objects:
                    self.assertEqual(item['metadata']['namespace'], 'kuadrant-system')
                    self.assertEqual(item['metadata']['labels']['workshop.user'], lab_id)
                self.assertEqual(objects[0]['rules'], [{
                    'apiGroups': ['apps'], 'resources': ['deployments'],
                    'resourceNames': ['authorino'], 'verbs': ['get']}])
                self.assertEqual(objects[1]['subjects'], [{
                    'kind': 'User', 'name': lab_id, 'apiGroup': 'rbac.authorization.k8s.io'}])
                self.assertEqual(objects[1]['roleRef'], {
                    'kind': 'Role', 'name': name, 'apiGroup': 'rbac.authorization.k8s.io'})

    def test_tenant_observability_is_gateway_local_and_least_privilege(self):
        role = ROOT / 'automation/common/roles/tenant'
        template = (role / 'templates/rbac.yaml.j2').read_text()
        expected_rules = [
            {'apiGroups': ['monitoring.coreos.com'], 'resources': ['podmonitors'],
             'verbs': ['get', 'list', 'watch']},
        ]
        for lab_id in ['user41', 'user92']:
            with self.subTest(lab_id=lab_id):
                gateway_namespace = 'gateway-' + lab_id
                documents = list(yaml.safe_load_all(RENDER.environment(role).from_string(template).render(
                    lab_id=lab_id, wk_ns_app='atp-' + lab_id,
                    wk_ns_gateway=gateway_namespace, tenant_ns_cert_manager='cert-manager')))
                name = lab_id + '-observability'
                objects = [item for item in documents if item['metadata']['name'] == name]
                self.assertEqual([item['kind'] for item in objects], ['Role', 'RoleBinding'])
                for item in objects:
                    self.assertEqual(item['apiVersion'], 'rbac.authorization.k8s.io/v1')
                    self.assertEqual(item['metadata']['namespace'], gateway_namespace)
                    self.assertEqual(item['metadata']['labels']['workshop.user'], lab_id)
                self.assertEqual(objects[0]['rules'], expected_rules)
                self.assertEqual(objects[1]['roleRef'], {
                    'kind': 'Role', 'name': name, 'apiGroup': 'rbac.authorization.k8s.io'})
                self.assertEqual(objects[1]['subjects'], [{
                    'kind': 'User', 'name': lab_id, 'apiGroup': 'rbac.authorization.k8s.io'}])
                # El nuevo permiso no crea grants globales ni en el namespace de la aplicación.
                self.assertEqual([item['kind'] for item in documents if 'rules' in item], ['Role', 'Role'])
                self.assertEqual(sum(item['kind'] == 'ClusterRoleBinding' for item in documents), 1)


if __name__ == '__main__':
    unittest.main()
