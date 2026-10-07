"""Control de fallos y propiedad del rol temporal, sin Kubernetes ni Keycloak."""
import copy
from pathlib import Path
import unittest

import yaml

from common_roles import run_tasks
from exact_quota import fixture_tasks

ROOT = Path(__file__).resolve().parents[3]
TASKS = ROOT / 'automation/labs/lab08/roles/lab08/tasks'


def restore_fixture():
    tasks = copy.deepcopy(yaml.safe_load((TASKS / 'restaurar_rol.yml').read_text()))
    tasks[0].pop('ansible.builtin.import_tasks')
    tasks[0]['block'] = [yaml.safe_load((TASKS / 'marcador_rol.yml').read_text())[1]]
    for task in tasks[1]['block']:
        if 'ansible.builtin.assert' in task:
            continue
        if 'ansible.builtin.import_tasks' in task:
            task.pop('ansible.builtin.import_tasks')
            task['ansible.builtin.debug'] = {'msg': 'MOCK_READ_CURRENT_UUID'}
        else:
            task.pop('ansible.builtin.include_tasks', None)
            task.pop('kubernetes.core.k8s', None)
            task['ansible.builtin.debug'] = {'msg': 'MOCK_REMOVE_ONLY_INVENTARIO' if 'vars' in task else 'MOCK_DELETE_MARKER'}
    return tasks


class Lab08Restoration(unittest.TestCase):
    def values(self, present=True):
        marker = {'metadata': {'labels': {'workshop.module': 'connectivity-link', 'workshop.user': 'demo'}},
                  'data': {'realm': 'realm-demo', 'user': 'alice', 'role': 'inventario',
                           'user_id': '00000000-0000-0000-0000-000000000001'}}
        return {'lab_id': 'demo', 'wk_realm': 'realm-demo', 'lab08_restaurar_rol': True,
                'lab08_alice_lectura': {'json': [{'username': 'alice', 'id': '00000000-0000-0000-0000-000000000001'}]},
                'lab08_marcador_rol': {'resources': [marker] if present else []}}

    def test_failure_after_assignment_restores_and_stays_failed(self):
        tasks = yaml.safe_load((TASKS / 'validar.yml').read_text())
        actual = copy.deepcopy(next(task for task in tasks if task['name'] == 'Registrar propiedad temporal y validar alice con el rol inventario'))
        actual['block'] = [{'name': 'Simular asignación completada', 'ansible.builtin.debug': {'msg': 'MOCK_ROLE_GRANTED'}},
                           {'name': 'Simular fallo posterior', 'ansible.builtin.fail': {'msg': 'MOCK_VALIDATION_FAILED'}}]
        # Conserva la condición y el bloque always reales; sustituye únicamente I/O.
        actual['always'][0]['block'] = restore_fixture()
        result = run_tasks([actual], self.values())
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MOCK_VALIDATION_FAILED', result.stdout)
        self.assertIn('MOCK_REMOVE_ONLY_INVENTARIO', result.stdout)
        self.assertIn('MOCK_DELETE_MARKER', result.stdout)

    def test_cleanup_without_owned_marker_never_changes_roles(self):
        result = run_tasks(restore_fixture(), self.values(False))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn('MOCK_REMOVE_ONLY_INVENTARIO', result.stdout)

    def test_initial_429_fails_quota_and_restores_temporary_role(self):
        tasks = yaml.safe_load((TASKS / 'validar.yml').read_text())
        actual = copy.deepcopy(next(task for task in tasks if task['name'] == 'Registrar propiedad temporal y validar alice con el rol inventario'))
        actual['block'] = fixture_tasks([429, 429, 429, 429])
        actual['always'][0]['block'] = restore_fixture()
        values = self.values()
        values.update(cuota_limite=3, cuota_ventana_segundos=60,
                      cuota_url='https://fixture.invalid/v1/items')
        result = run_tasks([actual], values)
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('MOCK_REMOVE_ONLY_INVENTARIO', result.stdout)
        self.assertIn('MOCK_DELETE_MARKER', result.stdout)

    def test_foreign_marker_cannot_remove_roles(self):
        values = self.values()
        values['lab08_marcador_rol']['resources'][0]['metadata']['labels']['workshop.user'] = 'other'
        result = run_tasks(restore_fixture(), values)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('MOCK_REMOVE_ONLY_INVENTARIO', result.stdout)

    def test_recreated_alice_uuid_cannot_lose_roles(self):
        values = self.values()
        values['lab08_alice_lectura']['json'][0]['id'] = '00000000-0000-0000-0000-000000000002'
        result = run_tasks(restore_fixture(), values)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('MOCK_REMOVE_ONLY_INVENTARIO', result.stdout)

    def test_preexisting_direct_or_inherited_role_cannot_create_marker(self):
        actual = yaml.safe_load((TASKS / 'marcar_rol.yml').read_text())
        # Ejecuta el assert real que precede cualquier escritura, con respuestas API simuladas.
        guard = actual[1]
        after_guard = {'name': 'Simular marcador', 'ansible.builtin.debug': {'msg': 'MOCK_CREATE_MARKER'}}
        for direct, effective in [(['inventario'], ['inventario']), ([], ['inventario'])]:
            values = self.values(False)
            values.update(lab08_roles_directos={'json': [{'name': name} for name in direct]},
                          lab08_roles_efectivos={'json': [{'name': name} for name in effective]},
                          mock_http_status=403)
            main = yaml.safe_load((TASKS / 'validar.yml').read_text())
            block = copy.deepcopy(next(task for task in main if task['name'] == 'Registrar propiedad temporal y validar alice con el rol inventario'))
            block['block'] = [guard, after_guard]
            block['always'][0]['block'] = restore_fixture()
            result = run_tasks([block], values)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('MOCK_CREATE_MARKER', result.stdout)
            self.assertNotIn('MOCK_REMOVE_ONLY_INVENTARIO', result.stdout)

    def test_unassigned_role_allows_marker_before_temporary_grant(self):
        actual = yaml.safe_load((TASKS / 'marcar_rol.yml').read_text())
        values = self.values(False)
        values.update(lab08_roles_directos={'json': [{'name': 'customer'}]},
                      lab08_roles_efectivos={'json': [{'name': 'customer'}]})
        result = run_tasks([actual[1], {'name': 'Simular marcador', 'ansible.builtin.debug': {'msg': 'MOCK_CREATE_MARKER'}}], values)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn('MOCK_CREATE_MARKER', result.stdout)


if __name__ == '__main__':
    unittest.main()
