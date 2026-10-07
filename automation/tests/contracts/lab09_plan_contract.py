"""Política efectiva de migración: verifica el assert real y la plantilla canónica."""
import copy
from pathlib import Path
import unittest

import jinja2
import yaml

from common_roles import run_tasks

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT / 'automation/labs/lab09/roles/lab09'
DEFAULTS = yaml.safe_load((ROLE / 'defaults/main.yml').read_text())
TEMPLATE = ROLE / 'templates/rate-limit.yaml.j2'
TASKS = yaml.safe_load((ROLE / 'tasks/validar.yml').read_text())
ASSERT = next(task for task in TASKS if 'lab09_rlp_esperada' in task.get('vars', {}))


class Lab09PlanContract(unittest.TestCase):
    def policy(self):
        rendered = jinja2.Environment(undefined=jinja2.StrictUndefined).from_string(TEMPLATE.read_text()).render(
            lab_id='fixture', wk_ns_app='app-fixture', **DEFAULTS)
        policy = yaml.safe_load(rendered)
        policy['status'] = {'conditions': [{'type': 'Enforced', 'status': 'True'}]}
        return policy

    def probe(self, policy):
        task = copy.deepcopy(ASSERT)
        # Mantiene el lookup canónico; solo resuelve la ubicación desde el play temporal.
        task['vars']['lab09_rlp_esperada'] = task['vars']['lab09_rlp_esperada'].replace('rate-limit.yaml.j2', str(TEMPLATE))
        return run_tasks([task], dict(DEFAULTS, lab_id='fixture', wk_ns_app='app-fixture',
                                     lab09_rlp_actual={'resources': [policy]}))

    def test_published_plans_and_application_counters_pass(self):
        result = self.probe(self.policy())
        self.assertEqual(result.returncode, 0, result.stdout)

    def test_wrong_quota_window_predicate_or_counter_fails(self):
        for field in ['limit', 'window', 'predicate', 'counter']:
            policy = self.policy()
            plan = policy['spec']['limits']['plan-premium']
            if field in ['limit', 'window']:
                plan['rates'][0][field] = 5 if field == 'limit' else '1s'
            elif field == 'predicate':
                plan['when'][0]['predicate'] = 'true'
            else:
                plan['counters'][0]['expression'] = 'auth.identity.plan'
            with self.subTest(field=field):
                self.assertNotEqual(self.probe(policy).returncode, 0)

    def test_gold_entry_missing_plan_wrong_target_and_unenforced_fail(self):
        for change in ['gold', 'missing', 'target', 'enforced']:
            policy = self.policy()
            if change == 'gold':
                policy['spec']['limits']['plan-gold'] = copy.deepcopy(policy['spec']['limits']['plan-premium'])
            elif change == 'missing':
                del policy['spec']['limits']['plan-bronze']
            elif change == 'target':
                policy['spec']['targetRef']['name'] = 'foreign-route'
            else:
                policy['status']['conditions'][0]['status'] = 'False'
            with self.subTest(change=change):
                self.assertNotEqual(self.probe(policy).returncode, 0)

    def test_gold_sample_exceeds_premium_without_claiming_universal_proof(self):
        gold = next(task for task in TASKS if task.get('vars', {}).get('cuota_sin_limite'))
        self.assertEqual(gold['ansible.builtin.include_role']['tasks_from'], 'probar_cuota_exacta')
        self.assertGreater(gold['vars']['cuota_muestra'], DEFAULTS['lab09_limites']['premium'])
        self.assertEqual(gold['vars']['cuota_json_contract'], '{{ wk_bank_json_contract }}')


if __name__ == '__main__':
    unittest.main()
