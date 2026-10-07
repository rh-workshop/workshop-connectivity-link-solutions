"""El estado agregado del Gateway no sustituye las pruebas de su ruta."""
import copy
from pathlib import Path
import unittest
import yaml
from common_roles import run_tasks

ROOT=Path(__file__).resolve().parents[3]
TASKS=yaml.safe_load((ROOT/'automation/labs/lab04b/roles/lab04b/tasks/main.yml').read_text())

class Override(unittest.TestCase):
    def test_single_and_multiple_routes_use_actual_condition(self):
        original=next(t for t in TASKS if t['name'].startswith('Esperar Overridden agregado'))
        self.assertEqual(original['ansible.builtin.include_role']['tasks_from'],'esperar_condicion')
        for listeners,expected in [([{'attachedRoutes':1}],True),([{'attachedRoutes':5}],False),
                                   ([{'attachedRoutes':1},{'attachedRoutes':1}],False),([],False)]:
            task=copy.deepcopy(original);task.pop('ansible.builtin.include_role')
            task['ansible.builtin.debug']={'msg':'WAIT_AGGREGATE_OVERRIDE'}
            result=run_tasks([task],{'lab04b_gateway_state':{'resources':[{'status':{'listeners':listeners}}]}})
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertEqual('WAIT_AGGREGATE_OVERRIDE' in result.stdout,expected,result.stdout)

    def test_route_enforcement_and_http_contract_remain(self):
        route=next(t for t in TASKS if t['name'].startswith('Esperar a la AuthPolicy de ruta Enforced'))
        self.assertEqual(route['vars']['espera_condicion'],'Enforced')
        tests=yaml.safe_load((ROOT/'automation/labs/lab04b/roles/lab04b/tasks/validar.yml').read_text())
        positive=next(t for t in tests if t['name']=='Con la clave válida')
        self.assertEqual(positive['vars']['http_esperado'],200)
        self.assertEqual(positive['vars']['http_json_contract'],'{{ wk_bank_json_contract }}')

if __name__=='__main__':unittest.main()
