"""Contratos Ansible locales: sustituyen I/O Kubernetes, nunca usan un clúster."""
import json
import os
import re
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[3]
ROLES = ROOT / 'automation/common/roles'


def run_tasks(tasks, variables):
    with tempfile.TemporaryDirectory() as folder:
        play = Path(folder) / 'test.yml'
        play.write_text(yaml.safe_dump([dict(hosts='localhost', gather_facts=False,
                                           vars=variables, tasks=tasks)], allow_unicode=True))
        env = dict(os.environ, ANSIBLE_CONFIG=str(ROOT / 'automation/ansible/ansible.cfg'),
                   ANSIBLE_NOCOLOR='1')
        return subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local',
                               '--forks', '1', str(play)], env=env,
                              capture_output=True, text=True)


class CommonRoles(unittest.TestCase):
    def test_resource_ownership(self):
        original = yaml.safe_load((ROLES / 'comun/tasks/asegurar_recurso.yml').read_text())
        for existing, update, success, writes in [([], False, True, True),
                ([{'metadata': {'labels': {'workshop.module': 'connectivity-link'}}}], True, True, True),
                ([{'metadata': {'labels': {'workshop.module': 'someone-else'}}}], True, False, False),
                ([{'metadata': {}}], False, True, False)]:
            with self.subTest(existing=existing, update=update):
                tasks = json.loads(json.dumps(original))
                tasks[0].pop('kubernetes.core.k8s_info')
                tasks[0].pop('register')
                tasks[0]['ansible.builtin.set_fact'] = {'comun_recurso_previo': {'resources': existing}}
                tasks[2].pop('kubernetes.core.k8s')
                tasks[2]['ansible.builtin.debug'] = {'msg': 'MOCK_WRITE_COMPLETED'}
                result = run_tasks(tasks, dict(recurso_definicion=dict(apiVersion='v1', kind='ConfigMap',
                                      metadata={'name': 'demo'}), recurso_actualizar_gestionado=update))
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
                self.assertEqual('MOCK_WRITE_COMPLETED' in result.stdout, writes, result.stdout)

    def test_destination_guards(self):
        tasks = yaml.safe_load((ROLES / 'comun/tasks/verificar_destino.yml').read_text())
        # Execute the actual assertions and their optional conditions, with read-only fixtures.
        assertions = [task for task in tasks if 'ansible.builtin.assert' in task]
        variables = dict(openshift_cluster_uid_esperado='uid-demo', openshift_infra_name_esperado='infra-demo',
                         openshift_console_domain_esperado='console.demo.invalid',
                         comun_identidad_namespace={'resources': [{'metadata': {'uid': 'uid-demo'}}]},
                         comun_identidad_infra={'resources': [{'status': {'infrastructureName': 'infra-demo'}}]},
                         comun_identidad_consola={'resources': [{'status': {'consoleURL': 'https://console.demo.invalid'}}]})
        result = run_tasks(assertions, variables)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        for key in ('openshift_cluster_uid_esperado', 'openshift_infra_name_esperado', 'openshift_console_domain_esperado'):
            with self.subTest(key=key):
                result = run_tasks(assertions, dict(variables, **{key: 'wrong'}))
                self.assertNotEqual(result.returncode, 0, result.stdout)
        result = run_tasks(assertions, {})
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_effective_api_guard(self):
        tasks = yaml.safe_load((ROLES / 'comun/tasks/main.yml').read_text())
        assertion = next(task for task in tasks if task['name'] == 'Comprobar que el cliente apunta a la API esperada')
        connection = next(task for task in tasks if 'kubernetes.core.k8s_cluster_info' in task)
        self.assertTrue(connection['no_log'])
        for host, expected, success in [('https://api.demo.invalid:6443', 'https://api.demo.invalid:6443', True),
                ('https://api.demo.invalid:6443/', 'https://api.demo.invalid:6443', True),
                ('https://other.invalid:6443', 'https://api.demo.invalid:6443', False)]:
            result = run_tasks([assertion], dict(comun_conexion={'connection': {'host': host}},
                                               openshift_api_esperada=expected))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_native_client_config_resolution(self):
        # Use Ansible's own Python/collection, not a second implementation of kubeconfig resolution.
        version = subprocess.run(['ansible-playbook', '--version'], capture_output=True, text=True, check=True)
        interpreter = re.search(r'python version = .*? \(([^()]+/python)\)', version.stdout).group(1)
        script = ("from ansible_collections.kubernetes.core.plugins.module_utils.k8s.client import "
                  "_create_auth_spec, _create_configuration; "
                  "print(_create_configuration(_create_auth_spec()).host)")
        with tempfile.TemporaryDirectory() as folder:
            first, second = Path(folder) / 'first.yml', Path(folder) / 'second.yml'
            for path, label, context in [(first, 'alpha', 'beta'), (second, 'beta', 'beta')]:
                path.write_text(yaml.safe_dump(dict(apiVersion='v1', kind='Config',
                    clusters=[dict(name=label, cluster={'server': f'https://{label}.invalid:6443'})],
                    contexts=[dict(name=label, context={'cluster': label, 'user': label})],
                    users=[dict(name=label, user={'token': 'fixture-only'})], **{'current-context': context})))
            base = {key: value for key, value in os.environ.items()
                    if not key.startswith('K8S_AUTH_') and key != 'KUBECONFIG'}
            base['K8S_AUTH_KUBECONFIG'] = str(first) + os.pathsep + str(second)
            for changes, expected in [({}, 'https://beta.invalid:6443'),
                    ({'K8S_AUTH_CONTEXT': 'alpha'}, 'https://alpha.invalid:6443'),
                    ({'K8S_AUTH_HOST': 'https://override.invalid:6443/'}, 'https://override.invalid:6443'),
                    ({'K8S_AUTH_CONTEXT': 'missing-context'}, None),
                    ({'K8S_AUTH_KUBECONFIG': str(Path(folder) / 'missing.yml')}, None)]:
                with self.subTest(changes=changes):
                    result = subprocess.run([interpreter, '-c', script], env=dict(base, **changes),
                                            capture_output=True, text=True)
                    if expected is None:
                        self.assertNotEqual(result.returncode, 0, result.stdout)
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertEqual(result.stdout.strip(), expected)

    def test_operator_group_scope(self):
        tasks = yaml.safe_load((ROLES / 'plataforma/tasks/operador.yml').read_text())
        assertion = next(task for task in tasks if 'ansible.builtin.assert' in task)
        for scope, groups, success in [(True, [], True), (True, [{'spec': {}}], True),
                (True, [{'spec': {'targetNamespaces': ['operator-ns']}}], False),
                (True, [{'spec': {'selector': {'matchLabels': {'a': 'b'}}}}], False),
                (True, [{'spec': {}}, {'spec': {}}], False),
                (False, [{'spec': {'targetNamespaces': ['operator-ns']}}], True),
                (False, [{'spec': {'targetNamespaces': ['other']}}], False)]:
            with self.subTest(scope=scope, groups=groups):
                result = run_tasks([assertion], dict(plataforma_operador_all_namespaces=scope,
                                    plataforma_ogs={'resources': groups}, plataforma_subs={'resources': []},
                                    operador={'namespace': 'operator-ns', 'nombre': 'paquete'}))
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        # Una Subscription existente al paquete se respeta aunque su OperatorGroup tenga otro alcance.
        result = run_tasks([assertion], dict(plataforma_operador_all_namespaces=True,
                            plataforma_ogs={'resources': [{'spec': {'targetNamespaces': ['operator-ns']}}]},
                            plataforma_subs={'resources': [{'spec': {'name': 'paquete'}}]},
                            operador={'namespace': 'operator-ns', 'nombre': 'paquete'}))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_operand_barriers_and_cold_absence(self):
        install = yaml.safe_load((ROLES / 'plataforma/tasks/instalar.yml').read_text())
        mesh_index = next(i for i, task in enumerate(install) if 'block' in task)
        mesh = install[mesh_index]['block']
        gates = [task for task in mesh if task.get('ansible.builtin.include_role', {}).get('tasks_from') == 'esperar_condicion']
        self.assertEqual([(task['vars']['espera_kind'], task['vars']['espera_condicion']) for task in gates],
                         [('IstioCNI', 'Ready'), ('Istio', 'Ready'), ('GatewayClass', 'Accepted')])
        self.assertTrue(all('when' not in task for task in gates))
        self.assertLess(mesh_index, next(i for i, task in enumerate(install)
                                        if task.get('kubernetes.core.k8s_info', {}).get('kind') == 'Kuadrant'))
        names = [task['name'] for task in mesh]
        self.assertLess(names.index(gates[0]['name']), names.index('Crear el namespace istio-system y el CR Istio'))
        webhook_index = next(i for i, task in enumerate(install)
                             if task.get('ansible.builtin.include_tasks') == 'esperar_webhook_cm.yml')
        self.assertLess(webhook_index, next(i for i, task in enumerate(install)
                                           if task.get('kubernetes.core.k8s_info', {}).get('kind') == 'ClusterIssuer'))
        original = yaml.safe_load((ROLES / 'comun/tasks/esperar_condicion.yml').read_text())
        for gate in gates:
            for resources, success in [([], False),
                    ([{'status': {'conditions': [{'type': gate['vars']['espera_condicion'], 'status': 'False'}]}}], False),
                    ([{'status': {'conditions': [{'type': gate['vars']['espera_condicion'], 'status': 'True'}]}}], True)]:
                tasks = json.loads(json.dumps(original))
                read = tasks[0]['block'][0]
                read.pop('kubernetes.core.k8s_info')
                read.pop('register')
                read['ansible.builtin.debug'] = {'msg': 'Read-only operand fixture'}
                variables = dict(gate['vars'], gateway_class='istio', espera_estado='True',
                                 comun_espera={'resources': resources}, k8s_espera_reintentos=1, k8s_espera_intervalo=0)
                result = run_tasks(tasks, variables)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_webhook_ready_addresses(self):
        tasks = yaml.safe_load((ROLES / 'plataforma/tasks/esperar_webhook_cm.yml').read_text())
        self.assertEqual(tasks[0]['vars']['espera_condicion'], 'Available')
        read = tasks[1]
        self.assertEqual(read['kubernetes.core.k8s_info']['label_selectors'],
                         ['kubernetes.io/service-name=cert-manager-webhook'])
        for resources, success in [([], False),
                ([{'endpoints': [{'addresses': ['192.0.2.1']}]}], False),
                ([{'endpoints': [{'conditions': {'ready': False}, 'addresses': ['192.0.2.1']}]}], False),
                ([{'endpoints': [{'conditions': {'ready': True}, 'addresses': []}]}], False),
                ([{'endpoints': [{'conditions': {'ready': True}, 'addresses': ['192.0.2.1']}]}], True)]:
            mock = json.loads(json.dumps(read))
            mock.pop('kubernetes.core.k8s_info')
            mock.pop('register')
            mock['ansible.builtin.debug'] = {'msg': 'Read-only Service fixture'}
            result = run_tasks([mock], dict(plataforma_webhook_endpoints={'resources': resources},
                                           k8s_espera_reintentos=1, k8s_espera_intervalo=0))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_cold_start_and_minimal_log_permissions(self):
        tasks = yaml.safe_load((ROLES / 'plataforma/tasks/instalar.yml').read_text())
        barrier = next(i for i, task in enumerate(tasks) if task.get('ansible.builtin.include_tasks') == 'esperar_apis.yml')
        cr_queries = [i for i, task in enumerate(tasks) if task.get('kubernetes.core.k8s_info', {}).get('kind') in ('CertManager', 'Kuadrant', 'ClusterIssuer')]
        self.assertTrue(cr_queries)
        self.assertTrue(all(barrier < i for i in cr_queries))
        apis = yaml.safe_load((ROLES / 'plataforma/tasks/esperar_apis.yml').read_text())
        self.assertEqual(apis[0]['ansible.builtin.include_tasks'], 'esperar_csv.yml')
        self.assertEqual(apis[1]['vars']['espera_condicion'], 'Established')
        roles = list(yaml.safe_load_all((ROLES / 'plataforma/templates/workshop-rbac.yaml.j2').read_text()))
        reader = next(role for role in roles if role['metadata']['name'] == 'workshop-operator-view')
        logs = [rule for rule in reader['rules'] if 'pods/log' in rule['resources']]
        self.assertEqual(logs, [{'apiGroups': [''], 'resources': ['pods/log'], 'verbs': ['get']}])
        common = yaml.safe_load((ROLES / 'comun/tasks/main.yml').read_text())
        self.assertTrue(any(task.get('ansible.builtin.import_tasks') == 'verificar_destino.yml' for task in common))
        self.assertFalse(any('kubernetes.core.k8s' in task for task in common))


if __name__ == '__main__':
    unittest.main()
