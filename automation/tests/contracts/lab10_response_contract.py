"""Contratos del JSON publicado de gobierno; solo sustituye la red del helper."""
import copy
from pathlib import Path
import unittest
import yaml
import http_content_contract

ROOT = Path(__file__).resolve().parents[3]
DEFAULTS = yaml.safe_load((ROOT / 'automation/labs/lab10/roles/lab10/defaults/main.yml').read_text())


class Lab10ResponseContract(unittest.TestCase):
    def payload(self, version='v1', method='GET'):
        body = {'service': 'gobierno-api', 'method': method, 'path': '/gobierno/v1/saldo', 'version': version}
        if version == 'v1':
            body['balance'] = '1250.40 EUR'
        else:
            body['saldo'] = {'cuenta': 'ACC-DEMO-001', 'moneda': 'EUR', 'disponible': 1250.40}
        return {'status': 200, 'content_type': 'application/json', 'json': body}

    def probe(self, response, method='GET'):
        contract = copy.deepcopy(DEFAULTS['lab10_http_contract'])
        # El método es el parámetro de cada operación; las demás reglas son canónicas.
        contract[1]['equals'] = method
        return http_content_contract.HttpContentContract().probe(response, contract)

    def test_published_get_post_and_both_versions_pass(self):
        for version in ['v1', 'v2']:
            for method in ['GET', 'POST']:
                result = self.probe(self.payload(version, method), method)
                self.assertEqual(result.returncode, 0, result.stdout)

    def test_http200_wrong_backend_method_path_version_or_balance_fails(self):
        for field, value in [('service', 'other-api'), ('method', 'POST'), ('path', '/different'),
                             ('version', 'unknown'), ('balance', '999 EUR')]:
            response = self.payload()
            response['json'][field] = value
            with self.subTest(field=field):
                self.assertNotEqual(self.probe(response).returncode, 0)

    def test_v2_saldo_requires_published_fields_values_and_no_v1_balance(self):
        for field, value in [('cuenta', 'OTHER'), ('moneda', 'USD'), ('disponible', '1250.40'),
                             ('disponible', 999)]:
            response = self.payload('v2')
            response['json']['saldo'][field] = value
            self.assertNotEqual(self.probe(response).returncode, 0)
        response = self.payload('v2')
        response['json']['balance'] = '1250.40 EUR'
        self.assertNotEqual(self.probe(response).returncode, 0)


if __name__ == '__main__':
    unittest.main()
