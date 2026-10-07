"""Ejecuta el control de errores canónico con I/O simulado, sin API real."""
import copy
from pathlib import Path
import unittest

import yaml

from common_roles import run_tasks

ROOT = Path(__file__).resolve().parents[3]
TASKS = ROOT / 'automation/labs/lab04b/roles/lab04b/tasks'


def restoration_fixture():
    tasks = yaml.safe_load((TASKS / 'restaurar.yml').read_text())
    def replace(items):
        output = []
        for task in items:
            task = copy.deepcopy(task)
            if 'block' in task:
                task['block'] = replace(task['block'])
                task['always'] = replace(task.get('always', []))
            elif task['name'] == 'Clave revocada':
                task.pop('ansible.builtin.include_role')
                task.pop('vars')
                task['ansible.builtin.fail'] = {'msg': 'MOCK_REVOCATION_CHECK_FAILED'}
                task['when'] = 'mock_revocation_failure | bool'
            else:
                for module in ('kubernetes.core.k8s', 'ansible.builtin.include_role'):
                    task.pop(module, None)
                task.pop('vars', None)
                task['ansible.builtin.debug'] = {'msg': 'MOCK_RESTORE_' + task['name']}
            output.append(task)
        return output
    return replace(tasks)


class Lab04bRestoration(unittest.TestCase):
    def main_fixture(self):
        block = copy.deepcopy(yaml.safe_load((TASKS / 'main.yml').read_text())[-1])
        validation = block['block'][0]
        validation.pop('ansible.builtin.import_tasks')
        validation['ansible.builtin.fail'] = {'msg': 'MOCK_VALIDATION_FAILED'}
        restore = block['always'][0]
        restore.pop('ansible.builtin.import_tasks')
        restore['block'] = restoration_fixture()
        return [block]

    def test_failed_validation_restores_and_remains_failed(self):
        result = run_tasks(self.main_fixture(), {'lab04b_validar': True, 'lab04b_restaurar_jwt': True,
                                                'mock_revocation_failure': False})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MOCK_VALIDATION_FAILED', result.stdout)
        self.assertIn('MOCK_RESTORE_Borrar la AuthPolicy de ruta', result.stdout)
        self.assertIn('MOCK_RESTORE_JWT restaurado', result.stdout)

    def test_failed_revocation_check_still_removes_authpolicy(self):
        result = run_tasks(restoration_fixture(), {'lab04b_validar': True, 'mock_revocation_failure': True})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MOCK_REVOCATION_CHECK_FAILED', result.stdout)
        self.assertIn('MOCK_RESTORE_Borrar la AuthPolicy de ruta', result.stdout)

    def test_explicit_no_restore_keeps_original_failure(self):
        result = run_tasks(self.main_fixture(), {'lab04b_validar': True, 'lab04b_restaurar_jwt': False,
                                                'mock_revocation_failure': False})
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('MOCK_VALIDATION_FAILED', result.stdout)
        self.assertNotIn('MOCK_RESTORE_', result.stdout)


if __name__ == '__main__':
    unittest.main()
