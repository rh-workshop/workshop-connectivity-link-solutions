"""Proyección y validación AWS con datos sintéticos, sin I/O de clúster."""
import json
from pathlib import Path
import unittest

import yaml

from common_roles import run_tasks
from render_contract import RENDER, FIXTURE

ROOT = Path(__file__).resolve().parents[3]
ANNOTATION = 'service.beta.kubernetes.io/aws-load-balancer-subnets'
TEMPLATES = {
    'lab03': 'gateway.yaml.j2',
    'lab07': 'gateway-cloud.yaml.j2',
    'lab11': 'gateway.yaml.j2',
}


class AwsSubnets(unittest.TestCase):
    def render(self, role_name, subnets=None, override=False):
        fixture = yaml.safe_load(FIXTURE.read_text())
        role = ROOT / f'automation/labs/{role_name}/roles/{role_name}'
        variables = yaml.safe_load((role / 'defaults/main.yml').read_text()) or {}
        variables.update(fixture['shared'])
        variables['aws_gateway_subnets_override'] = override
        variables.update(fixture['roles'].get(role_name, {}))
        if subnets is not None:
            variables['aws_load_balancer_subnet_ids'] = subnets
        rendered = RENDER.environment(role).from_string((role / 'templates' / TEMPLATES[role_name]).read_text()).render(**variables)
        return list(yaml.safe_load_all(rendered))

    def test_empty_profile_preserves_all_fields(self):
        for role in TEMPLATES:
            with self.subTest(role=role):
                self.assertEqual(self.render(role), self.render(role, []))
                gateway = self.render(role, [])[0]
                annotations = gateway['spec'].get('infrastructure', {}).get('annotations', {})
                self.assertNotIn(ANNOTATION, annotations)

    def test_three_subnets_project_without_other_changes(self):
        subnets = ['subnet-' + str(index) * 17 for index in range(3)]
        for role in TEMPLATES:
            with self.subTest(role=role):
                baseline = self.render(role, [])
                self.assertEqual(self.render(role, subnets), baseline)
                expected = json.loads(json.dumps(baseline))
                infrastructure = expected[0]['spec'].setdefault('infrastructure', {})
                infrastructure.setdefault('annotations', {})[ANNOTATION] = ','.join(subnets)
                self.assertEqual(self.render(role, subnets, True), expected)
        annotations = self.render('lab11', subnets, True)[0]['spec']['infrastructure']['annotations']
        self.assertEqual(annotations['service.beta.kubernetes.io/aws-load-balancer-proxy-protocol'], '*')
        self.assertIn('proxyProtocol', annotations['proxy.istio.io/config'])

    def test_actual_ansible_guard_rejects_types_ids_and_duplicates(self):
        tasks = yaml.safe_load((ROOT / 'automation/common/roles/comun/tasks/main.yml').read_text())
        guard = next(task for task in tasks if task['name'] == 'Validar la selección opcional de subnets AWS')
        valid = 'subnet-' + '0' * 17
        cases = [({}, True), ({'aws_load_balancer_subnet_ids': []}, True),
                 ({'aws_load_balancer_subnet_ids': [valid]}, True),
                 ({'aws_load_balancer_subnet_ids': valid}, False),
                 ({'aws_load_balancer_subnet_ids': [42]}, False),
                 ({'aws_load_balancer_subnet_ids': ['invalid']}, False),
                 ({'aws_load_balancer_subnet_ids': [valid, valid]}, False)]
        for values, success in cases:
            with self.subTest(values=values):
                result = run_tasks([guard], values)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
