"""Cuotas exactas: Ansible real con reloj y HTTP simulados, sin clúster."""
import os
import time
import unittest
from unittest.mock import patch
import yaml
from common_roles import ROOT, run_tasks

SOURCE = ROOT / 'automation/common/roles/comun/tasks/probar_cuota_exacta.yml'


def fixture_tasks(codes, duration=1, bad_body=False, source=SOURCE):
    tasks = yaml.safe_load(source.read_text())
    for task in tasks:
        if 'ansible.builtin.pause' in task:
            seconds = task.pop('ansible.builtin.pause')['seconds']
            task['ansible.builtin.assert'] = {'that': ['(' + seconds[3:-3] + ') | int == 61']}
        if 'ansible.builtin.command' in task:
            register = task.pop('register')
            task.pop('ansible.builtin.command')
            task.pop('changed_when')
            task.pop('delegate_to')
            task['ansible.builtin.set_fact'] = {register: {'stdout': str(1000 if register.endswith('inicio') else 1000 + duration)}}
        if task.get('ansible.builtin.include_role', {}).get('tasks_from') == 'probar_serie':
            task.pop('ansible.builtin.include_role')
            task['ansible.builtin.set_fact'] = {
                'wk_serie_codigos': codes,
                'comun_serie': {'results': [dict(status=code, content_type='application/json',
                    json={'path': '/wrong' if bad_body else '/v1/items'}) for code in codes]},
                'fixture_n': '{{ serie_n | int }}',
                'fixture_content': '{{ serie_contenido }}',
            }
    return tasks


class ExactQuota(unittest.TestCase):
    def run_fixture(self, codes, expected=True, duration=1, bad_body=False, **overrides):
        variables = dict(cuota_limite=3, cuota_url='https://fixture.invalid/v1/items',
                         cuota_ventana_segundos=60,
                         cuota_json_contract=[dict(path='path', equals='/v1/items')])
        variables.update(overrides)
        tasks = fixture_tasks(codes, duration, bad_body)
        if expected:
            tasks.append({'ansible.builtin.assert': {'that': [
                'fixture_n == ' + str(len(codes)), 'fixture_content == true']}})
        result = run_tasks(tasks, variables)
        self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)

    def test_published_three_successes_then_rejection(self):
        self.run_fixture([200, 200, 200, 429])

    def test_wrong_sequences_cannot_prove_quota(self):
        for codes in ([429] * 4, [200, 429, 429, 429], [200] * 4,
                      [200, 200, 429, 200], [200, 200, 200, 500]):
            with self.subTest(codes=codes):
                self.run_fixture(codes, expected=False)

    def test_window_crossing_and_clock_regression_fail(self):
        for duration in (60, 61, -1):
            self.run_fixture([200, 200, 200, 429], expected=False, duration=duration)

    def test_200_with_wrong_body_fails_without_another_request(self):
        self.run_fixture([200, 200, 200, 429], expected=False, bad_body=True)

    def test_finite_unlimited_sample(self):
        self.run_fixture([200] * 6, cuota_sin_limite=True, cuota_muestra=6)
        self.run_fixture([200] * 5 + [429], expected=False,
                         cuota_sin_limite=True, cuota_muestra=6)

    def test_invalid_parameters_fail_before_sample(self):
        for limit in (0, -1, 3.5, 'invalid'):
            self.run_fixture([200, 200, 200, 429], expected=False, cuota_limite=limit)

    def test_source_uses_shared_series_and_cached_contract(self):
        tasks = yaml.safe_load(SOURCE.read_text())
        includes = [task['ansible.builtin.include_role']['tasks_from'] for task in tasks
                    if 'ansible.builtin.include_role' in task]
        self.assertEqual(includes, ['probar_serie', 'validar_http_contrato'])
        self.assertFalse(any('ansible.builtin.uri' in task for task in tasks))
        clocks = [task for task in tasks if 'ansible.builtin.command' in task]
        self.assertEqual(len(clocks), 2)
        self.assertTrue(all(task['ansible.builtin.command'] == 'date +%s' and
                            task['delegate_to'] == 'localhost' for task in clocks))

    def test_actual_controller_clock_is_epoch_in_another_timezone(self):
        tasks = yaml.safe_load(SOURCE.read_text())
        clocks = [task for task in tasks if 'ansible.builtin.command' in task]
        before = int(time.time())
        clocks.append({'ansible.builtin.assert': {'that': [
            'cuota_exacta_inicio.stdout | int >= fixture_before',
            'cuota_exacta_fin.stdout | int <= fixture_before + 30',
            'cuota_exacta_fin.stdout | int >= cuota_exacta_inicio.stdout | int']}})
        with patch.dict(os.environ, {'TZ': 'America/Lima'}):
            result = run_tasks(clocks, {'fixture_before': before})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
