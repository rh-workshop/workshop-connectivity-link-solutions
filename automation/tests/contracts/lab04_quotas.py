"""Labs 4A/4B consumen el mismo contrato exacto, sin peticiones adicionales."""
import unittest
import yaml
from common_roles import ROOT, run_tasks
from exact_quota import fixture_tasks

class Lab04Quota(unittest.TestCase):
    def test_shared_five_request_contract_and_actual_semantics(self):
        common=yaml.safe_load((ROOT/'automation/common/roles/comun/defaults/main.yml').read_text())
        for lab in ['lab04a','lab04b']:
            tasks=yaml.safe_load((ROOT/f'automation/labs/{lab}/roles/{lab}/tasks/validar.yml').read_text())
            quota=next(t for t in tasks if t['name'].startswith('Comprobar cuota publicada'))
            self.assertEqual(quota['ansible.builtin.include_role']['tasks_from'],'probar_cuota_exacta')
            self.assertEqual(quota['vars']['cuota_limite'],5)
            self.assertEqual(quota['vars']['cuota_ventana_segundos'],60)
            self.assertEqual(quota['vars']['cuota_json_contract'],'{{ wk_bank_json_contract }}')
            for codes,party,success in [([200]*5+[429],'CL-BANK-DEMO',True),
                                         ([200]+[429]*5,'CL-BANK-DEMO',False),
                                         ([200]*6,'CL-BANK-DEMO',False),
                                         ([200]*5+[429],'WRONG-BACKEND',False)]:
                mocked=fixture_tasks(codes)
                for task in mocked:
                    facts=task.get('ansible.builtin.set_fact',{})
                    if 'comun_serie' in facts:
                        for row in facts['comun_serie']['results']:
                            row['json']={'Data':{'Party':{'PartyId':party,'name':'Backend de demo via Connectivity Link'}}}
                result=run_tasks(mocked,{'cuota_limite':5,'cuota_ventana_segundos':60,
                                        'cuota_url':'https://fixture.invalid/api/v1/party',
                                        'cuota_json_contract':common['wk_bank_json_contract']})
                self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
