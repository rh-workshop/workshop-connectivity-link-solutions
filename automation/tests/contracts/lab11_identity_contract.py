"""Los campos de identidad publicados no aceptan IPs parciales ni regex."""
import copy
from pathlib import Path
import unittest
import yaml
from common_roles import run_tasks

ROOT = Path(__file__).resolve().parents[3]
TASKS = yaml.safe_load((ROOT / 'automation/labs/lab11/roles/lab11/tasks/validar.yml').read_text())


class Lab11IdentityContract(unittest.TestCase):
    def probe(self, b2b=False, forwarded='203.0.113.10, 198.51.100.2', envoy='198.51.100.2', cn='socio-acme'):
        name = 'Comprobar la identidad que la capa 2 inyecta al backend' if b2b else 'Comprobar que la cabecera falsificada no sustituye a la IP real'
        assertion = next(t for t in TASKS if t['name'] == name)
        response = {'json': {'x_forwarded_for': forwarded, 'x_envoy_external_address': envoy,
                             'x_client_common_name': cn}}
        return run_tasks([copy.deepcopy(assertion)], {'wk_lab11_ip': '198.51.100.2',
                          'lab11_b2b' if b2b else 'lab11_eco': response})

    def test_exact_ip_in_forwarded_chain_passes(self):
        for b2b in [False, True]:
            result = self.probe(b2b)
            self.assertEqual(result.returncode, 0, result.stdout)

    def test_partial_or_regex_like_ip_fails(self):
        for b2b in [False, True]:
            for ip in ['198.51.100.20', '198x51x100x2', '1198.51.100.2']:
                with self.subTest(b2b=b2b, ip=ip):
                    self.assertNotEqual(self.probe(b2b, forwarded='203.0.113.10, '+ip).returncode, 0)

    def test_wrong_envoy_source_or_certificate_identity_fails(self):
        for b2b in [False, True]:
            self.assertNotEqual(self.probe(b2b, envoy='203.0.113.10').returncode, 0)
        self.assertNotEqual(self.probe(True, cn='socio-otro').returncode, 0)


if __name__ == '__main__':
    unittest.main()
