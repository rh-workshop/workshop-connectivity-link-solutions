"""Contratos HTTP publicados: sustituye únicamente la petición de red."""
import copy
from pathlib import Path
import unittest

import yaml

from common_roles import run_tasks

ROOT = Path(__file__).resolve().parents[3]
HTTP = ROOT / 'automation/common/roles/comun/tasks/probar_http.yml'
CONTRACT = [{'path': 'Data.Party.PartyId', 'equals': 'CL-BANK-DEMO'},
            {'path': 'Data.Party.name', 'equals': 'Backend de demo via Connectivity Link'}]


class HttpContentContract(unittest.TestCase):
    def probe(self, response, contract=CONTRACT, hidden=False):
        tasks = copy.deepcopy(yaml.safe_load(HTTP.read_text()))
        request = tasks[0]['block'][0]
        request.pop('ansible.builtin.uri')
        for key in ('register', 'until', 'retries', 'delay'):
            request.pop(key)
        request['ansible.builtin.set_fact'] = {'comun_http': response}
        # La fixture temporal conserva el helper canónico tras extraer su validación.
        for task in tasks[0]['block']:
            if task.get('ansible.builtin.import_tasks') == 'validar_http_contrato.yml':
                task['ansible.builtin.import_tasks'] = str(HTTP.parent / 'validar_http_contrato.yml')
        values = {'http_prueba': 'Public party contract', 'http_esperado': 200,
                  'http_json_contract': contract, 'http_no_log': hidden}
        return run_tasks(tasks, values)

    def payload(self):
        return {'status': 200, 'content_type': 'application/json; charset=utf-8',
                'json': {'Data': {'Party': {'PartyId': 'CL-BANK-DEMO',
                         'name': 'Backend de demo via Connectivity Link'}}}}

    def test_valid_published_party(self):
        self.assertEqual(self.probe(self.payload()).returncode, 0)

    def test_http200_wrong_body_missing_field_wrong_type_fail(self):
        for field, value in [('PartyId', 'OTHER-API'), ('PartyId', 42), ('name', None)]:
            response = self.payload()
            response['json']['Data']['Party'][field] = value
            with self.subTest(field=field, value=value):
                self.assertNotEqual(self.probe(response).returncode, 0)

    def test_http200_html_does_not_pass_as_json(self):
        self.assertNotEqual(self.probe({'status': 200, 'content_type': 'text/html', 'content': '<html>OK</html>'}).returncode, 0)

    def test_http200_missing_party_field_fails(self):
        response = self.payload()
        del response['json']['Data']['Party']['PartyId']
        self.assertNotEqual(self.probe(response).returncode, 0)

    def test_status_only_remains_compatible(self):
        self.assertEqual(self.probe({'status': 200}, []).returncode, 0)

    def test_wrong_payload_hidden_under_no_log(self):
        response = self.payload()
        response['json']['Data']['Party']['PartyId'] = 'SENSITIVE-RESPONSE'
        result = self.probe(response, hidden=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('SENSITIVE-RESPONSE', result.stdout + result.stderr)

    def test_lab4b_published_admin_audit_log(self):
        tasks = yaml.safe_load((ROOT / 'automation/labs/lab04b/roles/lab04b/tasks/validar.yml').read_text())
        contract = next(task for task in tasks if task['name'] == 'Rol admin en /admin')['vars']['http_json_contract']
        response = {'status': 200, 'content_type': 'application/json', 'json': {
            'Data': {'AuditLog': [{'Event': 'AccountRead', 'Actor': 'ACC-DEMO-001',
                                  'Timestamp': '2026-01-01T00:00:00Z'}]}}}
        self.assertEqual(self.probe(response, contract).returncode, 0)
        response['json']['Data']['AuditLog'][0]['Actor'] = 'OTHER-ACTOR'
        self.assertNotEqual(self.probe(response, contract).returncode, 0)

    def test_shared_premium_accounts_contract(self):
        defaults = yaml.safe_load((ROOT / 'automation/common/roles/comun/defaults/main.yml').read_text())
        response = {'status': 200, 'content_type': 'application/json', 'json': {
            'Data': {'Account': [{'AccountId': 'ACC-DEMO-001', 'Currency': 'EUR',
                                 'Nickname': 'Demo Savings'}]}}}
        self.assertEqual(self.probe(response, defaults['wk_bank_accounts_json_contract']).returncode, 0)
        response['json']['Data']['Account'][0]['Currency'] = 'USD'
        self.assertNotEqual(self.probe(response, defaults['wk_bank_accounts_json_contract']).returncode, 0)

    def test_lab9_accounts_uses_exact_quota_and_cached_json_contract(self):
        tasks = yaml.safe_load((ROOT / 'automation/labs/lab09/roles/lab09/tasks/validar.yml').read_text())
        premium = next(task for task in tasks if task.get('vars', {}).get('lab09_url_plan') == '{{ wk_api3_url }}/api/v1/accounts')
        self.assertEqual(premium['ansible.builtin.include_tasks'], 'plan.yml')
        self.assertEqual(premium['vars']['lab09_plan'], 'premium')
        self.assertEqual(premium['vars']['lab09_contrato_plan'], '{{ wk_bank_accounts_json_contract }}')
        plan = yaml.safe_load((ROOT / 'automation/labs/lab09/roles/lab09/tasks/plan.yml').read_text())[0]
        self.assertEqual(plan['ansible.builtin.include_role']['tasks_from'], 'probar_cuota_exacta')
        self.assertEqual(plan['vars']['cuota_limite'], '{{ lab09_limites[lab09_plan] }}')
        self.assertIn('lab09_contrato_plan', plan['vars']['cuota_json_contract'])


if __name__ == '__main__':
    unittest.main()
