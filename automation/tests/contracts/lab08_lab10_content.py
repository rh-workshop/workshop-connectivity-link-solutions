"""Ejecuta contratos canónicos con respuestas locales; no consulta el clúster."""
import copy
from pathlib import Path
import unittest
import yaml

from common_roles import run_tasks
import http_content_contract

ROOT = Path(__file__).resolve().parents[3]
LABS = ROOT / 'automation/labs'


def tasks(lab):
    return yaml.safe_load((LABS / lab / 'roles' / lab / 'tasks/validar.yml').read_text())


class Lab08Lab10Content(unittest.TestCase):
    def test_external_contract_accepts_exact_host_and_https_port(self):
        contract = next(t for t in tasks('lab08') if t['name'] == 'Inventario con el token de bob')['vars']['http_json_contract']
        contract = copy.deepcopy(contract)
        contract[2]['path'] = contract[2]['path'].replace('{{ wk_lab_host }}', 'api-user1.example.com')
        probe = http_content_contract.HttpContentContract().probe
        for host in ['api-user1.example.com', 'api-user1.example.com:443',
                     'evil-api-user1.example.com', 'api-user1.example.com.evil',
                     'api-user1.example.com:80']:
            response = {'status': 200, 'content_type': 'application/json',
                        'json': {'path': '/v1/items', 'authorization_recibida': False,
                                 'host_header': host}}
            with self.subTest(host=host):
                result = probe(response, contract)
                self.assertEqual(result.returncode == 0, host in ['api-user1.example.com', 'api-user1.example.com:443'], result.stdout)
        for field, value in [('path', '/inventario/items'), ('authorization_recibida', True),
                             ('authorization_recibida', 'false')]:
            response['json'] = {'path': '/v1/items', 'authorization_recibida': False,
                                'host_header': 'api-user1.example.com'}
            response['json'][field] = value
            with self.subTest(field=field, value=value):
                self.assertNotEqual(probe(response, contract).returncode, 0)

    def fixture(self, forced=False):
        defaults = yaml.safe_load((LABS / 'lab10/roles/lab10/defaults/main.yml').read_text())
        count = defaults['lab10_canary_muestra']
        v2_count = max(1, round(count * 0.1))
        rows = [{'status': 200, 'json': {'version': 'v1'}, 'deprecation': 'true',
                 'sunset': defaults['lab10_sunset'], 'link': 'successor-version'} for _ in range(count - v2_count)]
        rows += [{'status': 200, 'json': {'version': 'v2', 'saldo': {}}} for _ in range(v2_count)]
        if forced:
            rows = [{'status': 200, 'json': {'version': 'v2', 'saldo': {}}} for _ in range(5)]
        name = 'Comprobar que con la cabecera siempre responde v2, con saldo y sin aviso de retirada' if forced else 'Comprobar el 90/10 (con tolerancia) y Deprecation/Sunset/Link solo en v1'
        assertion = next(t for t in tasks('lab10') if t['name'] == name)
        return assertion, defaults, rows

    def check_canary(self, forced=False, change=None):
        assertion, defaults, rows = self.fixture(forced)
        if change:
            change(rows)
        values = dict(defaults, comun_serie={'results': rows}, wk_serie_codigos=[r['status'] for r in rows],
                      lab10_v1=[r for r in rows if r['json']['version'] == 'v1'],
                      lab10_v2=[r for r in rows if r['json']['version'] == 'v2'])
        return run_tasks([assertion], values)

    def test_valid_canary_and_forced_v2(self):
        for forced in [False, True]:
            result = self.check_canary(forced)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_unknown_version_in_sample_fails(self):
        result = self.check_canary(change=lambda rows: rows[0]['json'].update(version='other'))
        self.assertNotEqual(result.returncode, 0)

    def test_retirement_headers_on_v2_fail(self):
        for forced in [False, True]:
            for header in ['deprecation', 'sunset', 'link']:
                with self.subTest(forced=forced, header=header):
                    result = self.check_canary(forced, lambda rows: rows[-1].update({header: 'unexpected'}))
                    self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
