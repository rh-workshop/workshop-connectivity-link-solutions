"""La excepción de red omite solo autoritativos; HTTPS local sigue obligatorio."""
import copy
from pathlib import Path
import unittest

import yaml

from common_roles import run_tasks

ROOT = Path(__file__).resolve().parents[3]


class DnsEnvironmentGate(unittest.TestCase):
    def test_explicit_skip_preserves_local_https(self):
        original = yaml.safe_load((ROOT / 'automation/common/roles/comun/tasks/esperar_dns.yml').read_text())
        for flag in (None, True, False):
            tasks = copy.deepcopy(original)
            for task, module, marker in [(tasks[0]['block'][0], 'wk_dns_autoritativo', 'MOCK_AUTHORITATIVE_PROBE'),
                                         (tasks[1]['block'][0], 'ansible.builtin.uri', 'MOCK_LOCAL_HTTPS_PROBE')]:
                task.pop(module)
                for key in ('register', 'until', 'retries', 'delay'):
                    task.pop(key)
                task['ansible.builtin.debug'] = {'msg': marker}
            variables = {'dns_nombre': 'api.example.test'}
            if flag is not None:
                variables['dns_verificar_autoritativos'] = flag
            with self.subTest(flag=flag):
                result = run_tasks(tasks, variables)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertIn('MOCK_LOCAL_HTTPS_PROBE', result.stdout)
                self.assertEqual('MOCK_AUTHORITATIVE_PROBE' in result.stdout, flag is not False)


if __name__ == '__main__':
    unittest.main()
