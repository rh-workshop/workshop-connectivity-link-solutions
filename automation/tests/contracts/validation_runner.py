"""Runner offline: comandos simulados, dependencias y evidencias privadas."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'automation/scripts'))
SPEC = importlib.util.spec_from_file_location('runner', ROOT / 'automation/scripts/validate_labs.py')
RUNNER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RUNNER)
CATALOG = {entry['id']: entry for entry in yaml.safe_load((ROOT / 'automation/catalog.yml').read_text())['labs']}


class ValidationRunner(unittest.TestCase):
    def test_order_and_alias_come_from_catalog(self):
        rows = RUNNER.plan(CATALOG, ['lab04b', 'lab04', 'lab03', 'lab00'])
        self.assertEqual([row['id'] for row in rows], ['lab03', 'lab04a', 'lab04b', 'lab00'])
        with self.assertRaises(ValueError):
            RUNNER.plan(CATALOG, ['unknown'])

    def test_cycles_fail_closed(self):
        a = dict(CATALOG['lab03'], dependencies=['lab04a'])
        with self.assertRaisesRegex(ValueError, 'Ciclo'):
            RUNNER.plan(CATALOG | {'lab03': a}, ['lab03', 'lab04a'])

    def test_lab12_observability_precedes_validation(self):
        rows = RUNNER.plan(CATALOG, ['lab12', 'lab05', 'lab08'])
        self.assertEqual([row['id'] for row in rows], ['lab08', 'lab05', 'lab12'])
        self.assertIn('lab05', CATALOG['lab12']['external_dependencies'])

    def test_plan_never_invokes_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            def forbidden(*args, **kwargs):
                self.fail('Plan ejecutó un proceso')
            report = RUNNER.run(RUNNER.plan(CATALOG, ['lab00', 'lab01']), Path(folder), invoke=forbidden)
            # Lab00 tiene ahora un wrapper explícito; plan omite ambos procesos.
            # La navegación/login manual del catálogo no es el estado de ejecución del wrapper.
            self.assertEqual([r['status'] for r in report['results']], ['skipped', 'skipped'])
            self.assertFalse(report['executed'])
            self.assertEqual(list(Path(folder).glob('*.log')), [])

    def test_entry_without_wrapper_remains_manual_without_commands(self):
        with tempfile.TemporaryDirectory() as folder:
            def forbidden(*args, **kwargs):
                self.fail('Entrada manual ejecutó un proceso')
            entry = dict(CATALOG['lab00'], playbook=None)
            report = RUNNER.run([entry], Path(folder), invoke=forbidden)
            self.assertEqual(report['results'][0]['status'], 'manual')
            self.assertEqual(report['results'][0]['operation'], 'manual')
            self.assertEqual(list(Path(folder).glob('*.log')), [])

    def test_exit_codes_stop_sequence_and_logs_stay_private(self):
        calls = []
        def fake(command, **kwargs):
            calls.append(command)
            kwargs['stdout'].write('SENSITIVE-DEMO-TOKEN\n')
            return SimpleNamespace(returncode=0 if len(calls) == 1 else 5)
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            report = RUNNER.run(RUNNER.plan(CATALOG, ['lab01', 'lab02', 'lab03']), output,
                                Path('/private/values.yml'), {}, True, fake)
            self.assertEqual([r['status'] for r in report['results']], ['passed', 'failed', 'skipped'])
            self.assertEqual(len(calls), 2)
            self.assertNotIn('--tags', calls[0])
            self.assertEqual(calls[0][:2], ['ansible-playbook', 'playbooks/lab01.yml'])
            overrides = json.loads(calls[0][-1])
            self.assertIs(overrides['lab01_validar'], True)
            self.assertIs(overrides['lab12_demos'], False)
            serialized = (output / 'report.json').read_text()
            self.assertNotIn('SENSITIVE-DEMO-TOKEN', serialized)
            self.assertNotIn('/private/values.yml', serialized)
            for file in output.iterdir():
                self.assertEqual(file.stat().st_mode & 0o777, 0o600)

    def test_route_lab7_is_skipped_without_command(self):
        with tempfile.TemporaryDirectory() as folder:
            report = RUNNER.run(RUNNER.plan(CATALOG, ['lab07']), Path(folder), values={}, execute=False)
            self.assertEqual(report['results'][0]['status'], 'skipped')
        with tempfile.TemporaryDirectory() as folder:
            def forbidden(*args, **kwargs):
                self.fail('Lab7 route no debe ejecutar wrapper')
            report = RUNNER.run(RUNNER.plan(CATALOG, ['lab07']), Path(folder), Path('/private/values.yml'),
                                {'entrada_modo': 'route'}, True, forbidden)
            self.assertEqual(report['results'][0]['status'], 'skipped')

    def test_private_values_and_global_demos_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'values.yml'
            values = {'lab_id': 'demo', 'openshift_api_esperada': 'https://api.example.test:6443'}
            path.write_text(yaml.safe_dump(values))
            path.chmod(0o600)
            self.assertEqual(RUNNER.values_file(path)[1], values)
            path.chmod(0o644)
            with self.assertRaises(ValueError):
                RUNNER.values_file(path)
            path.chmod(0o600)
            for value in (True, 'true', '{{ dangerous_expression }}'):
                path.write_text(yaml.safe_dump(values | {'lab12_demos': value}))
                with self.assertRaisesRegex(ValueError, 'globales'):
                    RUNNER.values_file(path)

    def test_output_inside_repo_rejected(self):
        with self.assertRaises(ValueError):
            RUNNER.private_output(ROOT / 'private-report')

    def test_other_git_repositories_also_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            repository = Path(folder)
            (repository / '.git').mkdir()
            with self.assertRaises(ValueError):
                RUNNER.private_output(repository / 'report')

    def test_global_demos_denied_before_any_command(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, 'globales'):
                RUNNER.run(RUNNER.plan(CATALOG, ['lab12']), Path(folder),
                           Path('/private/values.yml'), {'lab12_demos': True}, True)


if __name__ == '__main__':
    unittest.main()
