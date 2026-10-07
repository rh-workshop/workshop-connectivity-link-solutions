"""Propiedad GitOps/bootstrap: pruebas Ansible con I/O sustituido, sin clúster."""
import json
from pathlib import Path
import unittest
import yaml
from common_roles import ROOT, ROLES, run_tasks


def bootstrap_tasks():
    """Expandir el import canónico real; conservar orden operador → instancia."""
    folder = ROLES / 'gitops_bootstrap/tasks'
    main = yaml.safe_load((folder / 'main.yml').read_text())
    result = []
    for task in main:
        if task.get('ansible.builtin.import_tasks') == 'operador.yml':
            result.extend(yaml.safe_load((folder / 'operador.yml').read_text()))
        else:
            result.append(task)
    return result


class GitOpsOwnership(unittest.TestCase):
    def test_platform_manager_guards(self):
        guards = yaml.safe_load((ROLES / 'comun/tasks/validar_gestor.yml').read_text())
        for variables, success in [({}, True), ({'plataforma_gestor': 'ansible', 'plataforma_escritura_solicitada': True}, True),
                ({'plataforma_gestor': 'argocd'}, True),
                ({'plataforma_gestor': 'argocd', 'plataforma_escritura_solicitada': True}, False),
                ({'plataforma_gestor': 'invalid'}, False)]:
            with self.subTest(variables=variables):
                result = run_tasks(guards, variables)
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_platform_and_observability_guard_before_writes(self):
        files = [ROLES / 'plataforma/tasks/instalar.yml', ROLES / 'plataforma/tasks/operador.yml',
                 ROLES / 'plataforma/tasks/keycloak_instancia.yml',
                 ROOT / 'automation/labs/lab05/roles/lab05/tasks/plataforma_instalar.yml',
                 ROOT / 'automation/labs/lab12/roles/lab12/tasks/demos.yml']
        for file in files:
            tasks = yaml.safe_load(file.read_text())
            self.assertEqual(tasks[0]['ansible.builtin.include_role']['tasks_from'], 'validar_gestor')
            self.assertTrue(tasks[0]['vars']['plataforma_escritura_solicitada'])
            # The real guard must fail before the following mocked write is executed.
            guard = {'ansible.builtin.import_tasks': str(ROLES / 'comun/tasks/validar_gestor.yml'),
                     'vars': tasks[0]['vars']}
            result = run_tasks([guard, {'ansible.builtin.debug': {'msg': 'SHARED_WRITE_EXECUTED'}}],
                               {'plataforma_gestor': 'argocd'})
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('SHARED_WRITE_EXECUTED', result.stdout)
        main = yaml.safe_load((ROLES / 'plataforma/tasks/main.yml').read_text())
        for verify, success in [(True, True), (False, False)]:
            result = run_tasks([{'ansible.builtin.import_tasks': str(ROLES / 'comun/tasks/validar_gestor.yml'),
                                 'vars': main[0]['vars']}],
                               dict(plataforma_gestor='argocd', plataforma_verificar_solo=verify))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_lab12_optional_demos_and_canonical_wrapper(self):
        main = yaml.safe_load((ROOT / 'automation/labs/lab12/roles/lab12/tasks/main.yml').read_text())
        self.assertEqual(main[0]['ansible.builtin.include_role']['tasks_from'], 'validar_gestor')
        for demos, success in [(False, True), (True, False)]:
            result = run_tasks([{'ansible.builtin.import_tasks': str(ROLES / 'comun/tasks/validar_gestor.yml'),
                                'vars': main[0]['vars']}], dict(plataforma_gestor='argocd', lab12_demos=demos))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        wrapper = yaml.safe_load((ROOT / 'automation/ansible/playbooks/gitops-bootstrap.yml').read_text())
        self.assertEqual([role['role'] for role in wrapper[0]['roles']], ['comun', 'gitops_bootstrap'])
        self.assertFalse(wrapper[0]['gather_facts'])

    def test_bootstrap_preserves_existing_operator_group(self):
        original = yaml.safe_load((ROLES / 'gitops_bootstrap/tasks/instalar.yml').read_text())
        for groups, success, expected_kinds in [([], True, ['Namespace', 'OperatorGroup', 'Subscription']),
                ([{'metadata': {'name': 'global-operators'}, 'spec': {}}], True, ['Namespace', 'Subscription']),
                ([{'spec': {'targetNamespaces': ['different']}}], False, []),
                ([{'spec': {}}, {'spec': {}}], False, [])]:
            tasks = json.loads(json.dumps(original))
            # Run the real mode guard using a local import (no role resolution/I/O).
            tasks[0] = {'ansible.builtin.import_tasks': str(ROLES / 'comun/tasks/validar_gestor.yml'),
                        'vars': original[0]['vars']}
            read = next(task for task in tasks if 'kubernetes.core.k8s_info' in task)
            read.pop('kubernetes.core.k8s_info')
            read.pop('register')
            read['ansible.builtin.set_fact'] = {'gitops_bootstrap_ogs': {'resources': groups}}
            create = tasks[-1]
            create.pop('ansible.builtin.include_role')
            create['ansible.builtin.set_fact'] = {'created_resources': '{{ created_resources | default([]) + [recurso_gitops] }}'}
            tasks.append({'ansible.builtin.assert': {'that':
                          "created_resources | map(attribute='kind') | list == expected_kinds"}})
            result = run_tasks(tasks, dict(plataforma_gestor='argocd', gitops_bootstrap_verificar_solo=False, expected_kinds=expected_kinds,
                     gitops_bootstrap_operador=dict(nombre='openshift-gitops-operator', namespace='openshift-operators', canal='latest')))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        explicit = next(task for task in original if task['name'] == 'Exigir bootstrap explícito antes de instalar GitOps')
        result = run_tasks([explicit], {'gitops_bootstrap_verificar_solo': True})
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_bootstrap_explicit_install_and_global_discovery(self):
        defaults = yaml.safe_load((ROLES / 'gitops_bootstrap/defaults/main.yml').read_text())
        self.assertIs(defaults['gitops_bootstrap_verificar_solo'], True)
        main = bootstrap_tasks()
        discovery = next(task for task in main if 'kubernetes.core.k8s_info' in task)
        self.assertNotIn('namespace', discovery['kubernetes.core.k8s_info'])
        branch = next(task for task in main if task.get('ansible.builtin.include_tasks') == 'instalar.yml')
        for verify, subscriptions, writes in [(True, [], False), (False, [], True),
                                             (False, [{'metadata': {'namespace': 'openshift-operators'}}], False)]:
            mock = json.loads(json.dumps(branch))
            mock.pop('ansible.builtin.include_tasks')
            mock['ansible.builtin.debug'] = {'msg': 'EXPLICIT_BOOTSTRAP_INSTALL'}
            result = run_tasks([mock], dict(gitops_bootstrap_verificar_solo=verify,
                                            gitops_bootstrap_subs_paquete=subscriptions))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual('EXPLICIT_BOOTSTRAP_INSTALL' in result.stdout, writes)
        namespace = next(task for task in main if 'gitops_bootstrap_namespace_efectivo' in task.get('ansible.builtin.set_fact', {}))
        result = run_tasks([namespace, {'ansible.builtin.assert': {'that': "gitops_bootstrap_namespace_efectivo == 'openshift-operators'"}}],
                 dict(gitops_bootstrap_subs_paquete=[{'metadata': {'namespace': 'openshift-operators'}}],
                      gitops_bootstrap_operador={'namespace': 'openshift-gitops-operator'}))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_bootstrap_readiness_and_lab06_adapter(self):
        main = bootstrap_tasks()
        csv = next(i for i, task in enumerate(main) if task.get('ansible.builtin.include_role', {}).get('tasks_from') == 'esperar_csv')
        crd = next(i for i, task in enumerate(main) if task.get('vars', {}).get('espera_nombre') == 'argocds.argoproj.io')
        instance = next(i for i, task in enumerate(main) if task.get('ansible.builtin.include_tasks') == 'esperar_argocd.yml')
        self.assertLess(csv, crd)
        self.assertLess(crd, instance)
        adapter = yaml.safe_load((ROOT / 'automation/labs/lab06/roles/lab06/tasks/plataforma.yml').read_text())
        self.assertEqual(len(adapter), 1)
        self.assertEqual(adapter[0]['ansible.builtin.include_role']['name'], 'gitops_bootstrap')
        original = yaml.safe_load((ROLES / 'gitops_bootstrap/tasks/esperar_argocd.yml').read_text())
        for resources, success in [([], False), ([{'status': {'phase': 'Pending'}}], False),
                                   ([{'status': {'phase': 'Available'}}], True)]:
            tasks = json.loads(json.dumps(original))
            read = tasks[0]['block'][0]
            read.pop('kubernetes.core.k8s_info')
            read.pop('register')
            read['ansible.builtin.debug'] = {'msg': 'Read-only ArgoCD fixture'}
            result = run_tasks(tasks, dict(gitops_bootstrap_argocd={'resources': resources},
                     gitops_bootstrap_argocd_instancia='openshift-gitops', gitops_bootstrap_argocd_namespace='openshift-gitops',
                     k8s_espera_reintentos=1, k8s_espera_intervalo=0))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
