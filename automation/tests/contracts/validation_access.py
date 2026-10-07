"""Contrato offline: monitorización readonly, scope e identidad existentes."""
from pathlib import Path
import unittest
import yaml
from jinja2 import Environment, StrictUndefined

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT/'automation/common/roles/validation_access'


class ValidationAccess(unittest.TestCase):
    def setUp(self):
        self.vars = {'lab_id':'user90', 'wk_ns_app':'atp-user90',
                     'validation_access_service_account':'validation-reader',
                     'validation_access_binding':'cl-validation-reader-user90'}
        self.tasks = yaml.safe_load((ROLE/'tasks/main.yml').read_text())

    def test_only_monitoring_view_and_one_scoped_subject(self):
        rendered = Environment(undefined=StrictUndefined).from_string(
            (ROLE/'templates/access.yml.j2').read_text()).render(**self.vars)
        sa, binding = list(yaml.safe_load_all(rendered))
        self.assertEqual(sa['kind'], 'ServiceAccount')
        self.assertFalse(sa['automountServiceAccountToken'])
        self.assertEqual(binding['roleRef'], {'apiGroup':'rbac.authorization.k8s.io',
                         'kind':'ClusterRole', 'name':'cluster-monitoring-view'})
        self.assertEqual(binding['subjects'], [{'kind':'ServiceAccount',
                         'name':'validation-reader', 'namespace':'atp-user90'}])
        self.assertEqual([sa['kind'], binding['kind']], ['ServiceAccount', 'ClusterRoleBinding'])
        self.assertNotIn('cluster-admin', rendered)

    def test_foreign_binding_rejected_by_real_assertions(self):
        env = Environment(undefined=StrictUndefined)
        env.filters['default'] = lambda value, default: value if value is not None else default
        task = next(t for t in self.tasks if 'sujetos diferentes' in t['name'])
        valid = {'metadata':{'labels':{'workshop.user':'user90','workshop.module':'connectivity-link'}},
                 'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'cluster-monitoring-view'},
                 'subjects':[{'kind':'ServiceAccount','name':'validation-reader','namespace':'atp-user90'}]}
        def accepted(obj):
            variables = dict(self.vars, validation_access_crb={'resources':[obj]})
            return all(env.compile_expression(expr)(**variables) for expr in task['ansible.builtin.assert']['that'])
        self.assertTrue(accepted(valid))
        import copy
        for field, value in [('roleRef', {'kind':'ClusterRole','name':'cluster-admin'}),
                             ('subjects', [{'kind':'ServiceAccount','name':'validation-reader','namespace':'foreign'}]),
                             ('metadata', {'labels':{'workshop.user':'foreign','workshop.module':'connectivity-link'}})]:
            changed = copy.deepcopy(valid)
            changed[field] = value
            self.assertFalse(accepted(changed))

    def test_readonly_default_and_no_token_operation(self):
        defaults = yaml.safe_load((ROLE/'defaults/main.yml').read_text())
        self.assertTrue(defaults['validation_access_verificar_solo'])
        writes = [t for t in self.tasks if 'kubernetes.core.k8s' in t]
        self.assertEqual(len(writes), 1)
        self.assertEqual(writes[0]['when'], 'not validation_access_verificar_solo | bool')
        self.assertFalse(any('ansible.builtin.command' in t or 'ansible.builtin.copy' in t for t in self.tasks))


if __name__ == '__main__':
    unittest.main()
