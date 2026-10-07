"""Ejecuta los contratos canónicos de métricas y tokens con fixtures locales."""
import copy
from pathlib import Path
import unittest
import yaml
from common_roles import run_tasks

ROOT = Path(__file__).resolve().parents[3]
LABS = ROOT / 'automation/labs'
PROMQL = yaml.safe_load((LABS / 'lab12/roles/lab12/tasks/promql_contract.yml').read_text())
USAGE = yaml.safe_load((LABS / 'bonus-ia/roles/bonus_tokens/tasks/usage_contract.yml').read_text())
LIMIT = yaml.safe_load((LABS / 'bonus-ia/roles/bonus_tokens/tasks/limit_contract.yml').read_text())


class Lab12BonusContract(unittest.TestCase):
    def vector(self):
        return {'status': 200, 'json': {'status': 'success', 'data': {'resultType': 'vector',
            'result': [{'metric': {'destination_service_name': 'bank-api', 'response_code': '429'},
                        'value': [1, '0.75']}]}}}

    def promql(self, response):
        return run_tasks(PROMQL, dict(lab12_promql=response, lab12_backend='bank-api',
                                     promql_codigos=True, promql_fraccion=True))

    def test_metric_contract_accepts_selected_backend(self):
        result = self.promql(self.vector())
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_wrong_metrics_shape_backend_nonfinite_and_ratio_fail(self):
        changes = [lambda r: r['json'].update(status='error'),
                   lambda r: r['json']['data'].update(resultType='matrix'),
                   lambda r: r['json']['data'].update(result=[]),
                   lambda r: r['json']['data']['result'][0]['metric'].update(destination_service_name='another-backend'),
                   lambda r: r['json']['data']['result'][0]['metric'].pop('response_code')]
        for value in ['NaN', '+Inf', '-Inf', '-0.1', '1.1']:
            changes.append(lambda r, v=value: r['json']['data']['result'][0].update(value=[1, v]))
        for change in changes:
            response = self.vector()
            change(response)
            self.assertNotEqual(self.promql(response).returncode, 0)

    def test_alert_state_must_belong_to_selected_backend(self):
        tasks = yaml.safe_load((LABS / 'lab12/roles/lab12/tasks/carga_alerta.yml').read_text())
        task = next(t for t in tasks[0]['block'] if 'ansible.builtin.set_fact' in t)
        for state, valid in [('pending', False), ('firing', True)]:
            rules = {'json': {'data': {'groups': [{'name': 'api-user1', 'rules': [
                {'name': 'CuotaAgotada', 'alerts': [
                    {'state': 'firing', 'labels': {'destination_service_name': 'another-backend'}},
                    {'state': state, 'labels': {'destination_service_name': 'bank-api'}}]}]}]}}}
            assertion = {'ansible.builtin.assert': {'that': 'lab12_alerta_ok == expected'}}
            result = run_tasks([task, assertion], dict(lab12_reglas=rules, lab_id='user1',
                lab12_backend='bank-api', lab12_alerta_estado='firing', lab12_ronda=0, expected=valid))
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_selected_backend_label_and_ratio_stay_paired(self):
        tasks = yaml.safe_load((LABS / 'lab12/roles/lab12/tasks/ronda_429.yml').read_text())
        task = next(t for t in tasks[0]['block'] if 'ansible.builtin.set_fact' in t)
        response = self.vector()
        response['json']['data']['result'] = [
            {'metric': {'destination_service_name': 'bank-api'}, 'value': [1, '0']},
            {'metric': {'destination_service_name': 'inventory.example.com'}, 'value': [1, '0.85']}]
        assertion = {'ansible.builtin.assert': {'that': "lab12_429_series == [['inventory.example.com', '0.85']]"}}
        result = run_tasks([task, assertion], dict(lab12_promql=response,
                           lab12_backend='inventory.example.com', lab12_ronda=0))
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_usage_sum_and_integer_types(self):
        for usage, valid in [({'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 30}, True),
                             ({'prompt_tokens': 20, 'completion_tokens': 10, 'total_tokens': 31}, False),
                             ({'prompt_tokens': '20', 'completion_tokens': 10, 'total_tokens': 30}, False),
                             ({'prompt_tokens': 0, 'completion_tokens': 0, 'total_tokens': 0}, False),
                             ({'total_tokens': 30}, False)]:
            result = run_tasks(USAGE, {'bonus_respuesta': {'json': {'usage': usage}}})
            self.assertEqual(result.returncode == 0, valid, result.stdout)

    def test_runtime_limit_must_match_cr_and_declared_budget(self):
        limit = {'max_value': 100, 'seconds': 60, 'conditions': ['route-condition'], 'variables': ['user_id']}
        for change, valid in [(None, True), ({'max_value': 3000}, False), ({'max_value': '100'}, False),
                              ({'seconds': 120}, False), ({'variables': ['other_user']}, False)]:
            runtime = copy.deepcopy(limit)
            if change:
                runtime.update(change)
            result = run_tasks(LIMIT, dict(bonus_limites_cr=[limit], bonus_limites_runtime=[runtime],
                                          bonus_tokens_limite=100, bonus_tokens_ventana='60s'))
            self.assertEqual(result.returncode == 0, valid, result.stdout)


if __name__ == '__main__':
    unittest.main()
