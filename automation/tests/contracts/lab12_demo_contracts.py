"""Demos globales: contratos reales con I/O simulado, sin clúster."""
import copy
import unittest
import yaml
from common_roles import ROOT, run_tasks
from exact_quota import fixture_tasks

DEMOS = ROOT / 'automation/labs/lab12/roles/lab12/tasks/demos.yml'
REPLICATED = ROOT / 'automation/common/roles/comun/tasks/probar_cuota_replicada.yml'


class DemoContracts(unittest.TestCase):
    def replicated(self, codes, duration=1, bad_body=False):
        return run_tasks(fixture_tasks(codes, duration, bad_body, REPLICATED), dict(
            cuota_url='https://fixture.invalid/v1/items', cuota_limite=3,
            cuota_replicas=2, cuota_muestra=12, cuota_ventana_segundos=60,
            cuota_json_contract=[dict(path='path', equals='/v1/items')]))

    def test_variable_distribution_is_not_fabricated_as_six_successes(self):
        for successes in (3, 5, 6):
            result = self.replicated([200] * successes + [429] * (12 - successes))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_errors_or_only_rejections_cannot_pass_as_local_quota(self):
        for codes in ([500] * 12, [429] * 12, [200] * 12,
                      [200] + [429] * 11, [200] * 2 + [429] * 10,
                      [200] * 7 + [429] * 5, [200] * 3 + [500] + [429] * 8):
            result = self.replicated(codes)
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_crossed_window_and_wrong_200_body_fail(self):
        codes = [200] * 3 + [429] * 9
        for duration in (60, -1):
            result = self.replicated(codes, duration)
            self.assertNotEqual(result.returncode, 0)
        self.assertNotEqual(self.replicated(codes, bad_body=True).returncode, 0)

    def test_initial_storage_guard_runs_before_any_global_mutation(self):
        tasks = yaml.safe_load(DEMOS.read_text())
        index = next(i for i, task in enumerate(tasks)
                     if task['name'].startswith('Exigir contadores en memoria'))
        demo_index = next(i for i, task in enumerate(tasks) if 'always' in task)
        self.assertLess(index, demo_index)
        for spec, success in [({}, True), ({'storage': {}}, True),
                              ({'storage': {'inMemory': {}}}, False),
                              ({'storage': {'redis': {'configSecretRef': {'name': 'foreign'}}}}, False),
                              ({'storage': {'redis-cached': {}}}, False),
                              ({'storage': {'disk': {}}}, False),
                              ({'storage': 'invalid'}, False)]:
            result = run_tasks([tasks[index]], {'lab12_orig_limitador': spec})
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_redis_uses_exact_contract_and_restored_authorino_checks_json(self):
        tasks = yaml.safe_load(DEMOS.read_text())
        demo = next(task for task in tasks if 'always' in task)
        redis = next(task for task in demo['block'] if task['name'].startswith('Comprobar tres respuestas'))
        self.assertEqual(redis['ansible.builtin.include_role']['tasks_from'], 'probar_cuota_exacta')
        self.assertEqual(redis['vars']['cuota_limite'], 3)
        self.assertIn('cuota_json_contract', redis['vars'])
        restored = next(task for task in demo['block'] if task['name'].startswith('Con Authorino restaurado'))
        self.assertEqual(restored['vars']['http_json_contract'], '{{ wk_bank_json_contract }}')
        samples = [i for i, task in enumerate(demo['block']) if
                   task.get('ansible.builtin.include_role', {}).get('tasks_from') in
                   ('probar_cuota_exacta', 'probar_cuota_replicada')]
        self.assertEqual(len(samples), 3)
        for index in samples:
            refresh = demo['block'][index - 1]
            self.assertEqual(refresh['ansible.builtin.include_role']['tasks_from'], 'token_keycloak')
            self.assertEqual(refresh['vars']['token_usuario'], 'bob')
            self.assertEqual(demo['block'][index]['vars']['cuota_cabeceras']['Authorization'],
                             'Bearer {{ wk_token }}')

    def test_bad_sample_preserves_failure_and_runs_all_original_restoration_steps(self):
        tasks = yaml.safe_load(DEMOS.read_text())
        demo = copy.deepcopy(next(task for task in tasks if 'always' in task))
        demo['block'] = fixture_tasks([500] * 12, source=REPLICATED)
        recovery = [task for task in demo['always'] if 'rescue' in task]
        original = [copy.deepcopy(task['block'][0]) for task in recovery]
        for i, task in enumerate(recovery):
            task['block'] = [{'ansible.builtin.debug': {'msg': 'RESTORE_' + str(i)}}]
        self.assertEqual([task.get('ansible.builtin.include_tasks') for task in original[:2]],
                         ['restaurar_authorino.yml', 'restaurar_limitador.yml'])
        self.assertEqual(original[2]['kubernetes.core.k8s']['name'], 'limitador-redis')
        result = run_tasks([demo], dict(cuota_url='https://fixture.invalid/v1/items',
            cuota_limite=3, cuota_replicas=2, cuota_muestra=12, cuota_ventana_segundos=60))
        self.assertNotEqual(result.returncode, 0)
        for i in range(3):
            self.assertIn('RESTORE_' + str(i), result.stdout)

    def test_restoration_failure_cannot_prevent_remaining_attempts_or_pass(self):
        tasks = yaml.safe_load(DEMOS.read_text())
        for failed_index in (0, 1, 2):
            demo = copy.deepcopy(next(task for task in tasks if 'always' in task))
            demo['block'] = [{'ansible.builtin.debug': {'msg': 'DEMO_SUCCEEDED'}}]
            recovery = [task for task in demo['always'] if 'rescue' in task]
            for i, task in enumerate(recovery):
                task['block'] = [{'ansible.builtin.debug': {'msg': 'ATTEMPT_' + str(i)}}]
                if i == failed_index:
                    task['block'].append({'ansible.builtin.fail': {'msg': 'RESTORATION_FAILED'}})
            result = run_tasks([demo], {})
            self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
            for i in range(3):
                self.assertIn('ATTEMPT_' + str(i), result.stdout)
            self.assertIn('Restauración incompleta', result.stdout)

    def test_successful_demo_and_all_restorations_can_pass(self):
        tasks = yaml.safe_load(DEMOS.read_text())
        demo = copy.deepcopy(next(task for task in tasks if 'always' in task))
        demo['block'] = [{'ansible.builtin.debug': {'msg': 'DEMO_SUCCEEDED'}}]
        for task in demo['always']:
            if 'rescue' in task:
                task['block'] = [{'ansible.builtin.debug': {'msg': 'RESTORATION_SUCCEEDED'}}]
        result = run_tasks([demo], {})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
