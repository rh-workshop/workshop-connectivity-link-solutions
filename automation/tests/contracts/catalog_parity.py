"""Fixtures offline: paridad real y rechazo de diferencias técnicas."""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest

import yaml

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('parity', ROOT / 'automation/scripts/check_parity.py')
PARITY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PARITY)
FIXTURE = ROOT / 'automation/tests/fixtures/parity-lab03.yml'


@unittest.skipUnless(PARITY.ROOT, PARITY.SKIP)
class ParityContract(unittest.TestCase):
    def run_fixture(self, fixture):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'fixture.yml'
            path.write_text(yaml.safe_dump(fixture))
            stdout, stderr = io.StringIO(), io.StringIO()
            with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                result = PARITY.check(path)
            return result, stdout.getvalue(), stderr.getvalue()

    def test_canonical_four_resources(self):
        result, output, _ = self.run_fixture(yaml.safe_load(FIXTURE.read_text()))
        self.assertEqual(result, 0)
        self.assertIn('4 recursos', output)

    def test_different_tls_issuer_is_not_ignored(self):
        fixture = yaml.safe_load(FIXTURE.read_text())
        fixture['jinja']['tls_issuer_name'] = 'different-issuer'
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn('$.spec.issuerRef.name: valor distinto', error)

    def test_different_gateway_identity_is_not_ignored(self):
        fixture = yaml.safe_load(FIXTURE.read_text())
        fixture['jinja']['wk_ns_gateway'] = 'different-namespace'
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn('0 heredocs con identidad', error)

    def test_empty_fixture_cannot_pass(self):
        fixture = yaml.safe_load(FIXTURE.read_text())
        fixture['templates'] = []
        with self.assertRaisesRegex(ValueError, 'sin plantillas'):
            self.run_fixture(fixture)

    def test_other_laboratories_compare_real_sources(self):
        for lab, count in [('lab04a', 4), ('lab04b', 2), ('lab05', 1), ('lab06', 2), ('lab07', 4), ('lab08', 5),
                           ('lab09', 8), ('lab10', 9), ('lab11', 15), ('lab12', 12), ('bonus-ia', 4)]:
            with self.subTest(lab=lab):
                fixture = yaml.safe_load(FIXTURE.with_name(f'parity-{lab}.yml').read_text())
                result, output, error = self.run_fixture(fixture)
                self.assertEqual(result, 0, error)
                self.assertIn(f'{count} recursos', output)

    def test_wrong_application_plan_and_token_quota_rejected(self):
        fixture = yaml.safe_load(FIXTURE.with_name('parity-lab09.yml').read_text())
        fixture['templates'][-1]['jinja']['item']['plan'] = 'wrong-plan'
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn('secret.kuadrant.io/plan: valor distinto', error)
        fixture = yaml.safe_load(FIXTURE.with_name('parity-bonus-ia.yml').read_text())
        fixture['jinja'] = {'bonus_tokens_limite': 999}
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn('rates[0].limit: valor distinto', error)

    def test_final_route_requires_unambiguous_source(self):
        fixture = yaml.safe_load(FIXTURE.with_name('parity-lab10.yml').read_text())
        fixture['templates'][-1].pop('heredoc_indices')
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn('2 heredocs con identidad', error)

    def test_gateway_ceiling_and_ip_range_divergence_rejected(self):
        for lab, variable, value, field in [('lab10', 'lab10_techo', 999, 'rates[0].limit'),
                                           ('lab11', 'lab11_bloque', '192.0.2.0/24', 'remoteIpBlocks[0]')]:
            fixture = yaml.safe_load(FIXTURE.with_name(f'parity-{lab}.yml').read_text())
            fixture.setdefault('jinja', {})[variable] = value
            result, _, error = self.run_fixture(fixture)
            self.assertEqual(result, 1)
            self.assertIn(f'{field}: valor distinto', error)

    def test_coverage_classifies_every_template_without_hiding_drift(self):
        fixtures = sorted(FIXTURE.parent.glob('parity-*.yml'))
        exclusions = FIXTURE.with_name('content-parity-exclusions.yml')
        self.assertEqual(PARITY.coverage(fixtures, exclusions), (42, 50, 8))
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'exclusions.yml'
            source = yaml.safe_load(exclusions.read_text())
            source['templates'].pop()
            path.write_text(yaml.safe_dump(source))
            with self.assertRaisesRegex(ValueError, 'Cobertura incompleta'):
                PARITY.coverage(fixtures, path)

    def test_external_route_preserves_authorization_removal_and_port(self):
        fixture = yaml.safe_load(FIXTURE.with_name('parity-lab08.yml').read_text())
        fixture['jinja'] = {'lab08_ext_port': 9999}
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn('port: valor distinto', error)

    def test_cloud_provider_and_issuer_are_not_ignored(self):
        for variable in ('lab07_dns_secret', 'lab07_acme_issuer'):
            fixture = yaml.safe_load(FIXTURE.with_name('parity-lab07.yml').read_text())
            fixture['jinja'] = {variable: 'wrong-reference'}
            result, _, error = self.run_fixture(fixture)
            self.assertEqual(result, 1)
            self.assertIn('valor distinto', error)

    def test_repeated_identity_requires_explicit_scenario(self):
        fixture = yaml.safe_load(FIXTURE.with_name('parity-lab04b.yml').read_text())
        fixture.pop('heredoc_indices')
        result, _, error = self.run_fixture(fixture)
        self.assertEqual(result, 1)
        self.assertIn('3 heredocs con identidad', error)

    def test_invalid_heredoc_selection_cannot_pass(self):
        fixture = yaml.safe_load(FIXTURE.read_text())
        for indices in ([], [0, 0], [100]):
            fixture['heredoc_indices'] = indices
            with self.assertRaisesRegex(ValueError, 'Selección de heredocs'):
                self.run_fixture(fixture)


if __name__ == '__main__':
    unittest.main()
