"""Defaults de clase: patch canónico y guardas ejecutadas sin I/O Kubernetes."""
import copy
from pathlib import Path
import unittest

from jinja2 import Environment, StrictUndefined
import yaml

from common_roles import run_tasks

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT / 'automation/common/roles/gateway_defaults'


class GatewayDefaults(unittest.TestCase):
    def variables(self):
        cm = {'metadata': {'name': 'workshop-istio-gateway-defaults', 'labels': {
            'workshop.module': 'connectivity-link', 'workshop.user': 'platform',
            'gateway.istio.io/defaults-for-class': 'istio'}}}
        return dict(gateway_class='istio', aws_load_balancer_subnet_ids=['subnet-' + '0' * 17],
                    gateway_defaults_namespace='istio-system', gateway_defaults_name='workshop-istio-gateway-defaults',
                    gateway_defaults_supported_versions=['v1.30.4', 'v1.30.5'],
                    gateway_defaults_istio={'resources': [{'spec': {'version': 'v1.30.5', 'namespace': 'istio-system'},
                        'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}]},
                    gateway_defaults_gateways={'resources': [{'metadata': {'name': 'demo', 'namespace': 'gateway-demo',
                        'labels': {'workshop.user': 'demo'}}, 'spec': {'gatewayClassName': 'istio'}}]},
                    gateway_defaults_namespaces={'resources': [{'metadata': {'name': 'gateway-demo',
                        'labels': {'workshop.module': 'connectivity-link', 'workshop.user': 'demo'}}}]},
                    gateway_defaults_named={'resources': [cm]}, gateway_defaults_labeled={'resources': [cm]})

    def test_service_patch_contains_only_subnet_annotation(self):
        values = self.variables()
        rendered = Environment(undefined=StrictUndefined).from_string((ROLE / 'templates/configmap.yaml.j2').read_text()).render(**values)
        cm = yaml.safe_load(rendered)
        patch = yaml.safe_load(cm['data']['service'])
        self.assertEqual(patch, {'metadata': {'annotations': {
            'service.beta.kubernetes.io/aws-load-balancer-subnets': ','.join(values['aws_load_balancer_subnet_ids'])}}})
        self.assertEqual(cm['metadata']['namespace'], 'istio-system')
        self.assertEqual(cm['metadata']['labels']['gateway.istio.io/defaults-for-class'], 'istio')
        self.assertNotIn('spec', patch)

    def test_guards_reject_shared_scope_and_ownership_problems(self):
        guards = yaml.safe_load((ROLE / 'tasks/guards.yml').read_text())
        cases = [('owned', self.variables(), True)]
        absent = self.variables()
        absent['gateway_defaults_named']['resources'] = []
        absent['gateway_defaults_labeled']['resources'] = []
        cases.append(('absent', absent, True))
        argocd = self.variables()
        argocd.update(plataforma_gestor='argocd', gateway_defaults_verificar_solo=True)
        argocd['gateway_defaults_named']['resources'][0]['metadata']['annotations'] = {'argocd.argoproj.io/sync-options': 'ServerSideApply=true'}
        cases.append(('Argo verify only', argocd, True))
        argocd_write = copy.deepcopy(argocd)
        argocd_write['gateway_defaults_verificar_solo'] = False
        cases.append(('Argo write rejected', argocd_write, False))
        for name, mutate in [
            ('foreign gateway user', lambda v: v['gateway_defaults_gateways']['resources'][0]['metadata']['labels'].update({'workshop.user': 'other'})),
            ('foreign namespace', lambda v: v['gateway_defaults_namespaces']['resources'][0]['metadata']['labels'].update({'workshop.module': 'other'})),
            ('foreign configmap', lambda v: v['gateway_defaults_named']['resources'][0]['metadata']['labels'].update({'workshop.module': 'other'})),
            ('operator owner', lambda v: v['gateway_defaults_named']['resources'][0]['metadata'].update({'ownerReferences': [{'kind': 'Istio'}]})),
            ('duplicate defaults', lambda v: v['gateway_defaults_labeled']['resources'].append(copy.deepcopy(v['gateway_defaults_labeled']['resources'][0]))),
            ('unsupported version', lambda v: v['gateway_defaults_istio']['resources'][0]['spec'].update({'version': 'v1.29.0'})),
            ('not Ready', lambda v: v['gateway_defaults_istio']['resources'][0]['status']['conditions'][0].update({'status': 'False'})),
            ('different root namespace', lambda v: v['gateway_defaults_istio']['resources'][0]['spec'].update({'values': {'meshConfig': {'rootNamespace': 'other'}}})),
        ]:
            values = self.variables()
            mutate(values)
            cases.append((name, values, False))
        for name, variables, expected in cases:
            with self.subTest(name=name):
                result = run_tasks(guards, variables)
                self.assertEqual(result.returncode == 0, expected, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
