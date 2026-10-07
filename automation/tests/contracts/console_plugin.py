"""Vendor workaround: ownership, actual local strategic merge, readonly defaults."""
import copy
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from common_roles import ROOT, ROLES, run_tasks

ROLE = ROLES / 'console_plugin_configuration'


def deployment():
    return dict(apiVersion='apps/v1', kind='Deployment',
                metadata=dict(name='kuadrant-console-plugin', namespace='kuadrant-system', generation=3,
                              labels={'app.kubernetes.io/managed-by': 'kuadrant-operator',
                                      'app.kubernetes.io/name': 'kuadrant-console-plugin',
                                      'app.kubernetes.io/instance': 'kuadrant-console-plugin'}, annotations={'keep': 'unchanged'}),
                spec=dict(replicas=1, template=dict(metadata={'labels': {'keep': 'unchanged'}}, spec=dict(containers=[
                    dict(name='kuadrant-console-plugin', image='fixture:latest', env=[
                        {'name': 'OTHER', 'value': 'keep'},
                        {'name': 'METRICS_WORKLOAD_SUFFIX', 'valueFrom': {'configMapKeyRef': {'name': 'fixture', 'key': 'suffix'}}}],
                        resources={'limits': {'memory': '256Mi'}}),
                    dict(name='sidecar', image='fixture:sidecar', env=[{'name': 'OTHER', 'value': 'untouched'}])]))),
                status=dict(observedGeneration=3, conditions=[{'type': 'Available', 'status': 'True'}]))


class ConsolePlugin(unittest.TestCase):
    def test_authorino_endpoint_matches_parent_default_endpoint(self):
        source = yaml.safe_load((ROOT/'automation/labs/lab05/roles/lab05/tasks/plataforma_verificar.yml').read_text())
        assertion = next(task for task in source if task.get('name') ==
                         'Comprobar la observabilidad y el tracing del CR Kuadrant y de Authorino')
        endpoint = 'rpc://otel-collector.tempo.svc.cluster.local:4317'
        parent = {'enable': True, 'tracing': {'defaultEndpoint': endpoint},
                  'dataPlane': {'httpHeaderIdentifier': 'x-request-id'}}
        # Authorino v1beta1 exposes endpoint, not the parent's defaultEndpoint.
        for child, success in [({'endpoint': endpoint, 'insecure': True}, True),
                               ({'endpoint': 'rpc://wrong:4317'}, False),
                               ({'defaultEndpoint': endpoint}, False), ({}, False)]:
            with self.subTest(child=child):
                result = run_tasks([assertion], {'lab05_kuadrant_obs': parent,
                                                'lab05_authorino_tracing': child})
                self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)

    def test_operator_ownership_argocd_absent(self):
        guards = yaml.safe_load((ROLE/'tasks/validar_propiedad.yml').read_text())
        changes = [{}, {'labels': {'app.kubernetes.io/managed-by': 'someone-else'}},
                   {'name': 'another-deployment'}, {'namespace': 'another-namespace'},
                   {'annotations': {'argocd.argoproj.io/tracking-id': 'application:apps/Deployment:ns/name'}},
                   {'annotations': {'argocd.argoproj.io/installation-id': 'instance'}},
                   {'labels': {'argocd.argoproj.io/instance': 'application'}},
                   {'managedFields': [{'manager': 'argocd-controller'}]},
                   {'ownerReferences': [{'kind': 'Application', 'name': 'application'}]}]
        for change in changes:
            resource = deployment()
            for key, value in change.items():
                if isinstance(value, dict): resource['metadata'].setdefault(key, {}).update(value)
                else: resource['metadata'][key] = value
            result = run_tasks(guards, dict(console_plugin_actual={'resources': [resource]},
                                           console_plugin_deployment='kuadrant-console-plugin', console_plugin_namespace='kuadrant-system'))
            self.assertEqual(result.returncode == 0, not change, result.stdout+result.stderr)
        result = run_tasks(guards, dict(console_plugin_actual={'resources': []}, console_plugin_deployment='kuadrant-console-plugin', console_plugin_namespace='kuadrant-system'))
        self.assertNotEqual(result.returncode, 0)

    def test_official_local_strategic_merge_preserves_other_fields(self):
        source = yaml.safe_load((ROLE/'tasks/patch.yml').read_text())[-1]['kubernetes.core.k8s']
        self.assertEqual(source['merge_type'], 'strategic-merge')
        with tempfile.TemporaryDirectory() as folder:
            path, patch = Path(folder)/'deployment.json', Path(folder)/'patch.json'
            before = deployment()
            path.write_text(json.dumps(before))
            result = run_tasks([{'ansible.builtin.copy': {'dest': str(patch), 'content': '{{ source_definition | to_json }}'}}],
                               dict(source_definition=source['definition'], console_plugin_contenedor='kuadrant-console-plugin', console_plugin_sufijo='-istio'))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            result = subprocess.run(['oc', 'patch', '--local', '--kubeconfig=/dev/null', '-f', str(path),
                                     '--type=strategic', '--patch-file', str(patch), '-o', 'json'], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            after = json.loads(result.stdout)
            wanted = copy.deepcopy(before)
            wanted['spec']['template']['spec']['containers'][0]['env'][1] = {'name': 'METRICS_WORKLOAD_SUFFIX', 'value': '-istio'}
            self.assertEqual(after, wanted)

    def test_patch_only_explicit_and_changed(self):
        main = yaml.safe_load((ROLE/'tasks/main.yml').read_text())
        branch = next(task for task in main if task.get('ansible.builtin.include_tasks') == 'patch.yml')
        for verify, env, changed in [(True, [], False), (False, [], True),
                (False, [{'name': 'METRICS_WORKLOAD_SUFFIX', 'value': '-istio'}], False),
                (False, [{'name': 'METRICS_WORKLOAD_SUFFIX', 'value': '-openshift-default'}], True),
                (False, [{'name': 'METRICS_WORKLOAD_SUFFIX', 'valueFrom': {'configMapKeyRef': {'name': 'fixture', 'key': 'suffix'}}}], True)]:
            mock = copy.deepcopy(branch)
            mock.pop('ansible.builtin.include_tasks')
            mock['ansible.builtin.debug'] = {'msg': 'PLUGIN_PATCH_EXECUTED'}
            result = run_tasks([mock], dict(console_plugin_verificar_solo=verify, console_plugin_env_actual=env, console_plugin_sufijo='-istio'))
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
            self.assertEqual('PLUGIN_PATCH_EXECUTED' in result.stdout, changed)
        guard = {'ansible.builtin.import_tasks': str(ROLES/'comun/tasks/validar_gestor.yml'), 'vars': main[0]['vars']}
        result = run_tasks([guard], {'plataforma_gestor': 'argocd'})
        self.assertEqual(result.returncode, 0, result.stdout+result.stderr)
        defaults = yaml.safe_load((ROLE/'defaults/main.yml').read_text())
        self.assertTrue(defaults['console_plugin_verificar_solo'])

    def test_readiness_observed_generation_and_suffix(self):
        source = yaml.safe_load((ROLE/'tasks/verificar.yml').read_text())[0]
        for ready, generation, suffix, success in [(True, 3, '-istio', True), (False, 3, '-istio', False),
                                                   (True, 2, '-istio', False), (True, 3, '-openshift-default', False)]:
            resource = deployment()
            resource['status']['observedGeneration'] = generation
            resource['status']['conditions'][0]['status'] = 'True' if ready else 'False'
            resource['spec']['template']['spec']['containers'][0]['env'][1] = {'name': 'METRICS_WORKLOAD_SUFFIX', 'value': suffix}
            mock = copy.deepcopy(source)
            mock.pop('kubernetes.core.k8s_info'); mock.pop('register')
            mock['ansible.builtin.debug'] = {'msg': 'Read-only Deployment fixture'}
            result = run_tasks([mock], dict(console_plugin_final={'resources': [resource]}, console_plugin_contenedor='kuadrant-console-plugin',
                               console_plugin_sufijo='-istio', k8s_espera_reintentos=1, k8s_espera_intervalo=0))
            self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)


if __name__ == '__main__':
    unittest.main()
