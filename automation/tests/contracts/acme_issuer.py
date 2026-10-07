"""Contratos ACME canónicos, ejecutados localmente sin AWS/Kubernetes."""
import base64
import json
import unittest
import yaml
from common_roles import ROOT, ROLES, run_tasks

ROLE = ROLES / 'acme_issuer'


def variables():
    return dict(acme_issuer_nombre='letsencrypt-dns01', acme_email='',
                acme_servidor='https://acme-v02.api.letsencrypt.org/directory', acme_issuer_kind='ClusterIssuer', acme_issuer_namespace='',
                acme_secret_nombre='acme-route53-credentials', acme_secret_namespace='cert-manager',
                acme_cuenta_secret='letsencrypt-dns01-account', acme_route53_hosted_zone_id='ZDEMO123',
                acme_dns_zone='public.example.invalid', acme_route53_region='us-east-2',
                acme_issuer_verificar_solo=True, acme_issuer_secret_bootstrap=False,
                dns_provider_datos=dict(AWS_ACCESS_KEY_ID='fixture-access', AWS_SECRET_ACCESS_KEY='fixture-secret', AWS_REGION='us-east-2'))


class AcmeIssuer(unittest.TestCase):
    def participant(self):
        return dict(variables(), lab_id='user91', acme_issuer_participant_mode=True,
                    acme_issuer_nombre='letsencrypt-dns01-user91',
                    acme_secret_nombre='acme-route53-credentials-user91',
                    acme_cuenta_secret='letsencrypt-dns01-user91-account')

    def test_participant_scope_rejects_shared_and_other_names(self):
        tasks = yaml.safe_load((ROLE / 'tasks/validar.yml').read_text())
        for change, success in [({}, True), ({'acme_issuer_nombre': 'letsencrypt-dns01'}, False),
                ({'acme_secret_nombre': 'acme-route53-credentials-user90'}, False),
                ({'acme_cuenta_secret': 'shared-account'}, False),
                ({'acme_issuer_kind': 'Issuer'}, False)]:
            result = run_tasks(tasks, dict(self.participant(), **change))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_participant_secret_no_rotation_and_no_argo_adoption(self):
        tasks = yaml.safe_load((ROLE / 'tasks/secret.yml').read_text())
        guard = next(task for task in tasks if task['name'].startswith('Impedir rotación'))
        # El harness ejecuta la tarea fuera del rol: sólo fija la ruta de lookup.
        guard['ansible.builtin.assert']['that'] = guard['ansible.builtin.assert']['that'].replace(
            "'secret.yaml.j2'", repr(str(ROLE / 'templates/secret.yaml.j2')))
        values = self.participant()
        data = {key: base64.b64encode(values['dns_provider_datos'][key].encode()).decode()
                for key in ['AWS_ACCESS_KEY_ID', 'AWS_SECRET_ACCESS_KEY']}
        own = {'metadata': {'labels': {'workshop.user': 'user91'}}, 'data': data}
        for resources, success in [([], True), ([own], True),
                ([dict(own, metadata={'labels': {'workshop.user': 'user90'}})], False),
                ([dict(own, data=dict(data, AWS_SECRET_ACCESS_KEY=base64.b64encode(b'changed').decode()))], False),
                ([dict(own, metadata={'labels': {'workshop.user': 'user91'},
                                     'annotations': {'argocd.argoproj.io/tracking-id': 'owned'}})], False)]:
            result = run_tasks([guard], values | {'acme_secret_previo': {'resources': resources}})
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        reconcile = next(task for task in tasks if task['name'].startswith('Reconciliar'))
        self.assertTrue(any('resources | length == 0' in rule for rule in reconcile['when']))
        self.assertIn('acme_issuer_secret_bootstrap | bool or not acme_issuer_verificar_solo | bool', reconcile['when'])
        self.assertTrue(guard['no_log'])

    def test_participant_bootstrap_isolated_and_shared_argocd_stays_blocked(self):
        wrapper = yaml.safe_load((ROOT / 'automation/ansible/playbooks/lab07-acme.yml').read_text())
        self.assertEqual([role['role'] for role in wrapper[0]['roles']], ['comun'])
        self.assertEqual(wrapper[0]['tasks'][0]['ansible.builtin.include_role']['tasks_from'], 'acme_prepare')
        main = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        for participant, success in [(False, False), (True, True)]:
            result = run_tasks([{'ansible.builtin.import_tasks': str(ROLES / 'comun/tasks/validar_gestor.yml'),
                                'vars': main[0]['vars']}],
                               dict(plataforma_gestor='argocd', acme_issuer_verificar_solo=False,
                                    acme_issuer_participant_mode=participant))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_parameters_fail_closed(self):
        tasks = yaml.safe_load((ROLE / 'tasks/validar.yml').read_text())
        for change, success in [({}, True), ({'acme_email': 'instructor@example.invalid'}, True),
                ({'acme_route53_hosted_zone_id': ''}, False), ({'acme_dns_zone': ''}, False),
                ({'acme_route53_region': ''}, False), ({'acme_email': 'fake-contact'}, False),
                ({'acme_secret_namespace': 'participant'}, False),
                ({'acme_issuer_kind': 'Issuer', 'acme_issuer_namespace': 'openshift-ingress', 'acme_secret_namespace': 'openshift-ingress'}, True),
                ({'acme_issuer_kind': 'Issuer', 'acme_issuer_namespace': 'openshift-ingress', 'acme_secret_namespace': 'cert-manager'}, False), ({'acme_servidor': 'http://acme.invalid/directory'}, False)]:
            with self.subTest(change=change):
                result = run_tasks(tasks, dict(variables(), **change))
                self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_canonical_templates_email_and_secret_refs(self):
        # Use actual Ansible filters/template lookup; never render real credentials.
        for email, kind in [('', 'ClusterIssuer'), ('instructor@example.invalid', 'ClusterIssuer'), ('', 'Issuer')]:
            values = dict(variables(), acme_email=email, acme_issuer_kind=kind,
                          acme_issuer_namespace='openshift-ingress' if kind == 'Issuer' else '',
                          acme_secret_namespace='openshift-ingress' if kind == 'Issuer' else 'cert-manager')
            tasks = [{'ansible.builtin.set_fact': {
                        'rendered_issuer': "{{ lookup('ansible.builtin.template', '" + str(ROLE / 'templates/cluster-issuer.yaml.j2') + "') | from_yaml }}",
                        'rendered_secret': "{{ lookup('ansible.builtin.template', '" + str(ROLE / 'templates/secret.yaml.j2') + "') | from_yaml }}"}},
                     {'ansible.builtin.assert': {'that': [
                        "rendered_issuer.spec.acme.email | default('') == acme_email",
                        "('email' in rendered_issuer.spec.acme) == (acme_email | length > 0)",
                        "rendered_issuer.spec.acme.solvers[0].selector.dnsZones == [acme_dns_zone]",
                        "rendered_issuer.spec.acme.solvers[0].dns01.route53.hostedZoneID == acme_route53_hosted_zone_id",
                        "rendered_issuer.spec.acme.solvers[0].dns01.route53.accessKeyIDSecretRef.name == rendered_secret.metadata.name",
                        "rendered_issuer.spec.acme.solvers[0].dns01.route53.secretAccessKeySecretRef.name == rendered_secret.metadata.name",
                        "rendered_secret.data.AWS_ACCESS_KEY_ID | b64decode == dns_provider_datos.AWS_ACCESS_KEY_ID",
                        "rendered_secret.data.AWS_SECRET_ACCESS_KEY | b64decode == dns_provider_datos.AWS_SECRET_ACCESS_KEY",
                        "'stringData' not in rendered_secret",
                        "rendered_secret.metadata.namespace == acme_secret_namespace",
                        "rendered_issuer.kind == acme_issuer_kind",
                        "rendered_issuer.metadata.namespace | default('') == acme_issuer_namespace",
                        "'fixture-secret' not in rendered_issuer | to_json",
                        "'fixture-access' not in rendered_issuer | to_json"]}}]
            result = run_tasks(tasks, values)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        public = (ROLE / 'templates/cluster-issuer.yaml.j2').read_text()
        self.assertNotIn('dns_provider_datos', public)

    def test_secret_ownership_and_no_log(self):
        tasks = yaml.safe_load((ROLE / 'tasks/secret.yml').read_text())
        sensitive = [task for task in tasks if task['name'] not in ('Exigir bootstrap explícito para credenciales DNS', 'Validar el gestor antes del bootstrap de Secret')]
        self.assertTrue(all(task.get('no_log') is True for task in sensitive))
        guard = next(task for task in tasks if task['name'].startswith('Rechazar credenciales'))
        for resources, success in [([], True), ([{'metadata': {'labels': {'workshop.module': 'connectivity-link', 'workshop.component': 'acme-issuer'}}}], True),
                ([{'metadata': {'labels': {'workshop.module': 'connectivity-link'}}}], False),
                ([{'metadata': {}}], False)]:
            result = run_tasks([guard], {'acme_secret_previo': {'resources': resources}})
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_argocd_issuer_block_and_secret_bootstrap_exception(self):
        main = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        for verify, success in [(True, True), (False, False)]:
            result = run_tasks([{'ansible.builtin.import_tasks': str(ROLES / 'comun/tasks/validar_gestor.yml'),
                                'vars': main[0]['vars']}], dict(plataforma_gestor='argocd', acme_issuer_verificar_solo=verify))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        secret = yaml.safe_load((ROLE / 'tasks/secret.yml').read_text())
        for explicit, success in [(True, True), (False, False)]:
            result = run_tasks([next(task for task in secret if task['name'] == 'Exigir bootstrap explícito para credenciales DNS')], dict(plataforma_gestor='argocd', acme_issuer_verificar_solo=True,
                                               acme_issuer_secret_bootstrap=explicit))
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)
        issuer = yaml.safe_load((ROLE / 'tasks/issuer.yml').read_text())
        self.assertTrue(issuer[0]['vars']['plataforma_escritura_solicitada'])

    def test_observability_wrapper_explicit_opt_in(self):
        wrapper = yaml.safe_load((ROOT / 'automation/ansible/playbooks/observability-bootstrap.yml').read_text())
        self.assertEqual([role['role'] for role in wrapper[0]['roles']], ['comun'])
        self.assertEqual(wrapper[0]['tasks'][1]['ansible.builtin.include_role'],
                         {'name': 'lab05', 'tasks_from': 'plataforma_instalar'})
        self.assertFalse(wrapper[0]['tasks'][1]['vars']['lab05_reiniciar_gateway'])
        installer = yaml.safe_load((ROOT / 'automation/labs/lab05/roles/lab05/tasks/plataforma_instalar.yml').read_text())
        restart = next(task for task in installer if task['name'].startswith('Reiniciar el Gateway'))
        for restart_gateway, changed, writes in [(False, True, False), (True, True, True), (True, False, False)]:
            mock = dict(restart)
            mock.pop('kubernetes.core.k8s')
            mock['ansible.builtin.debug'] = {'msg': 'PARTICIPANT_GATEWAY_RESTART'}
            result = run_tasks([mock], dict(lab05_reiniciar_gateway=restart_gateway,
                                            lab05_istio_parche={'changed': changed}))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual('PARTICIPANT_GATEWAY_RESTART' in result.stdout, writes)
        for variables_, success in [({}, False), ({'lab05_plataforma_verificar_solo': True}, False),
                                   ({'lab05_plataforma_verificar_solo': False}, True)]:
            result = run_tasks([wrapper[0]['tasks'][0]], variables_)
            self.assertEqual(result.returncode == 0, success, result.stdout + result.stderr)

    def test_readiness_order_and_defaults(self):
        tasks = yaml.safe_load((ROLE / 'tasks/main.yml').read_text())
        names = [task['name'] for task in tasks]
        crd = next(i for i, task in enumerate(tasks) if task.get('vars', {}).get('espera_condicion') == 'Established')
        webhook = next(i for i, task in enumerate(tasks) if task.get('ansible.builtin.include_role', {}).get('tasks_from') == 'esperar_webhook_cm')
        issuer = next(i for i, task in enumerate(tasks) if task.get('ansible.builtin.include_tasks') == 'issuer.yml')
        self.assertLess(crd, webhook)
        self.assertLess(webhook, issuer)
        ready = yaml.safe_load((ROLE / 'tasks/verificar.yml').read_text())
        self.assertEqual(ready[-1]['vars']['espera_condicion'], 'Ready')
        defaults = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
        self.assertTrue(defaults['acme_issuer_verificar_solo'])
        self.assertFalse(defaults['acme_issuer_secret_bootstrap'])
        self.assertEqual(defaults['acme_email'], '')
        self.assertEqual(defaults['acme_servidor'], variables()['acme_servidor'])
        wrapper = yaml.safe_load((ROOT / 'automation/ansible/playbooks/acme-issuer.yml').read_text())
        self.assertEqual([role['role'] for role in wrapper[0]['roles']], ['comun', 'acme_issuer'])


if __name__ == '__main__':
    unittest.main()
