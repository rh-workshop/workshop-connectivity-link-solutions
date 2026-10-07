"""Habilitación externa: contratos reales y CAS local, sin API de clúster."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import yaml
from common_roles import ROOT, ROLES, run_tasks
from console_plugin import deployment

ROLE = ROLES / 'console_plugin_configuration'
READ = yaml.safe_load((ROLE/'tasks/habilitacion.yml').read_text())
WRITE = yaml.safe_load((ROLE/'tasks/habilitacion_patch.yml').read_text())
NAME = 'kuadrant-console-plugin'


def console(plugins=None, omit=False):
    result = {'apiVersion': 'operator.openshift.io/v1', 'kind': 'Console',
              'metadata': {'name': 'cluster', 'uid': 'console-uid', 'resourceVersion': '12'},
              'spec': {'managementState': 'Managed', 'customization': {'brand': 'fixture'}}}
    if not omit:
        result['spec']['plugins'] = [NAME] if plugins is None else plugins
    return result


class ConsolePluginEnabled(unittest.TestCase):
    def values(self, resource=None, verify=True):
        return dict(console_plugin_deployment=NAME, console_plugin_namespace='kuadrant-system',
                    console_plugin_verificar_solo=verify,
                    console_plugin_console={'resources': [console() if resource is None else resource]})

    def test_verify_enabled_missing_and_duplicate(self):
        assertions = [t for t in READ if 'ansible.builtin.assert' in t
                      and t['name'] != 'Exigir registro correcto y backend Available con generación observada']
        for plugins, success in [([NAME], True), (['networking', NAME, 'monitoring'], True),
                                 ([], False), ([NAME, NAME], False)]:
            result = run_tasks(assertions, self.values(console(plugins)))
            self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)

    def test_documented_cli_boolean_strings_and_invalid_mode(self):
        for value, success in [('true', True), ('false', True), ('ambiguous', False), (1, False)]:
            result = run_tasks([READ[0]], self.values(verify=value))
            self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)

    def test_registration_and_available_observed_backend(self):
        assertion = next(t for t in READ if t['name'] == 'Exigir registro correcto y backend Available con generación observada')
        registration = {'resources': [{'spec': {'backend': {'type': 'Service', 'service': {
            'name': NAME, 'namespace': 'kuadrant-system'}}}}]}
        for change in ['none', 'namespace', 'service', 'unavailable', 'generation', 'absent']:
            values = self.values();values['console_plugin_registration'] = copy.deepcopy(registration)
            values['console_plugin_backend'] = {'resources': [deployment()]}
            if change in ['namespace', 'service']:
                values['console_plugin_registration']['resources'][0]['spec']['backend']['service'][
                    'namespace' if change == 'namespace' else 'name'] = 'foreign'
            elif change == 'unavailable':
                values['console_plugin_backend']['resources'][0]['status']['conditions'][0]['status'] = 'False'
            elif change == 'generation':
                values['console_plugin_backend']['resources'][0]['status']['observedGeneration'] = 2
            elif change == 'absent':
                values['console_plugin_registration']['resources'] = []
            result = run_tasks([assertion], values)
            self.assertEqual(result.returncode == 0, change == 'none', result.stdout+result.stderr)

    def patch(self, resource):
        task = next(t for t in WRITE if 'ansible.builtin.set_fact' in t)
        with tempfile.TemporaryDirectory() as d:
            path = Path(d)/'patch.json'
            save = {'ansible.builtin.copy': {'dest': str(path), 'content': '{{ console_plugin_enable_patch | to_json }}'}}
            result = run_tasks([task, save], self.values(resource, verify=False))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            return json.loads(path.read_text())

    def apply_local(self, resource, patch):
        with tempfile.TemporaryDirectory() as d:
            source, changes = Path(d)/'console.json', Path(d)/'patch.json'
            source.write_text(json.dumps(resource));changes.write_text(json.dumps(patch))
            return subprocess.run(['oc', 'patch', '--local=true', '--type=json', '-f', str(source),
                                   '--patch-file', str(changes), '-o', 'json'], text=True, capture_output=True)

    def test_cas_append_preserves_existing_plugins_and_all_other_fields(self):
        before = console(['networking', 'monitoring', 'tracing'])
        patch = self.patch(before);result = self.apply_local(before, patch)
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = copy.deepcopy(before);expected['spec']['plugins'].append(NAME)
        self.assertEqual(json.loads(result.stdout), expected)
        self.assertEqual([p['op'] for p in patch], ['test', 'test', 'test', 'add'])
        self.assertEqual(patch[-1]['path'], '/spec/plugins/-')

    def test_absent_list_adds_only_plugins_and_preserves_other_spec(self):
        before = console(omit=True);result = self.apply_local(before, self.patch(before))
        self.assertEqual(result.returncode, 0, result.stderr)
        expected = copy.deepcopy(before);expected['spec']['plugins'] = [NAME]
        self.assertEqual(json.loads(result.stdout), expected)

    def test_stale_uid_version_or_list_rejected_before_append(self):
        original = console(['networking']);patch = self.patch(original)
        for field in ['uid', 'resourceVersion', 'plugins']:
            stale = copy.deepcopy(original)
            if field == 'plugins':
                stale['spec']['plugins'].append('concurrent-plugin')
            else:
                stale['metadata'][field] = 'changed'
            self.assertNotEqual(self.apply_local(stale, patch).returncode, 0)

    def test_verify_and_already_enabled_do_not_enter_write_branch(self):
        branch = copy.deepcopy(next(t for t in READ if 'ansible.builtin.include_tasks' in t))
        branch.pop('ansible.builtin.include_tasks');branch['ansible.builtin.debug'] = {'msg': 'ENABLE_PATCH_ENTERED'}
        for verify, plugins, changed in [(True, [], False), (True, [NAME], False),
                                         (False, [NAME], False), (False, [], True)]:
            result = run_tasks([branch], self.values(console(plugins), verify))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual('ENABLE_PATCH_ENTERED' in result.stdout, changed)

    def test_foreign_argocd_ownership_and_missing_explicit_permission_rejected(self):
        guards = [t for t in WRITE if 'ansible.builtin.assert' in t]
        cases = [({'annotations': {'argocd.argoproj.io/tracking-id': 'foreign'}}, False),
                 ({'annotations': {'argocd.argoproj.io/installation-id': 'foreign'}}, False),
                 ({'labels': {'argocd.argoproj.io/instance': 'foreign'}}, False),
                 ({'managedFields': [{'manager': 'argocd-controller'}]}, False),
                 ({'ownerReferences': [{'kind': 'Application', 'name': 'foreign'}]}, False),
                 ({}, True)]
        for metadata, success in cases:
            obj = console([]);obj['metadata'].update(metadata)
            result = run_tasks(guards, self.values(obj, verify=False))
            self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
        self.assertNotEqual(run_tasks(guards, self.values(console([]), verify=True)).returncode, 0)

    def test_lab1_reuses_readonly_activation_without_metrics_workaround(self):
        tasks = yaml.safe_load((ROOT/'automation/labs/lab01/roles/lab01/tasks/validar.yml').read_text())
        task = next(t for t in tasks if t.get('ansible.builtin.include_role', {}).get('name') == 'console_plugin_configuration')
        self.assertEqual(task['ansible.builtin.include_role']['tasks_from'], 'habilitacion')
        self.assertTrue(task['vars']['console_plugin_verificar_solo'])


if __name__ == '__main__':
    unittest.main()
