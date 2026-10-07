"""Carga finita y contratos HA: fixtures locales, sin acceso al clúster."""
import importlib.util
import json
import unittest
from unittest.mock import Mock
import requests
import yaml
from common_roles import ROOT, run_tasks

spec=importlib.util.spec_from_file_location('workload',ROOT/'automation/common/roles/comun/library/wk_http_workload.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
TASKS=yaml.safe_load((ROOT/'automation/labs/lab12/roles/lab12/tasks/authorino_ha.yml').read_text())
def task(name):
    for t in TASKS:
        if t['name']==name:return t
        for t2 in t.get('block',[])+t.get('always',[]):
            if t2['name']==name:return t2
    raise KeyError(name)
class HA(unittest.TestCase):
    def response(self,status=200,body=None):
        r=Mock(status_code=status,headers={'Content-Type':'application/json'})
        r.__enter__=Mock(return_value=r);r.__exit__=Mock(return_value=False)
        r.iter_content=Mock(return_value=[json.dumps(body or {'Data':{'Party':{'PartyId':'CL-BANK-DEMO','name':'Backend de demo via Connectivity Link'}}}).encode()])
        return r
    def test_finite_parallel_requests_preserve_cached_json(self):
        fetch=Mock(side_effect=[self.response(200 if i<5 else 429) for i in range(300)])
        result=module.workload('https://fixture.invalid',{'Authorization':'private'},300,20,45,fetch=fetch)
        self.assertEqual(fetch.call_count,300)
        self.assertEqual(sum(r['status']==200 for r in result['results']),5)
        self.assertIn('json',result['results'][0]);self.assertLess(result['duration'],60)
        for call in fetch.call_args_list:
            self.assertFalse(call.kwargs['verify']);self.assertFalse(call.kwargs['allow_redirects'])
    def test_timeout_transport_and_non_json_are_not_success(self):
        fetch=Mock(side_effect=requests.Timeout('private-detail'))
        result=module.workload('https://fixture.invalid',{},1,1,45,fetch=fetch)
        self.assertEqual(result['results'],[{'status':-1,'error':'Timeout'}])
        r=self.response();r.iter_content.return_value=[b'<html>not JSON</html>']
        result=module.workload('https://fixture.invalid',{},1,1,45,fetch=lambda *a,**k:r)
        self.assertNotIn('json',result['results'][0])
        clock=Mock(side_effect=[0,46,47])
        result=module.workload('https://fixture.invalid',{},1,1,45,clock=clock,fetch=fetch)
        self.assertEqual(result['results'][0]['error'],'deadline')
    def test_exact_codes_and_window(self):
        assertion=task('Exigir cuota publicada dentro de una única ventana')
        for codes,duration,good in [([200]*5+[429]*295,1,True),([200]*6+[429]*294,1,False),([200]*5+[429]*294+[401],1,False),([200]*5+[429]*295,60,False)]:
            result=run_tasks([assertion],{'lab12_ha_workload':{'results':[{'status':c} for c in codes],'duration':duration}})
            self.assertEqual(result.returncode==0,good,result.stdout+result.stderr)
    def test_restore_rejects_recreated_or_changed_resource(self):
        assertion=task('Exigir identidad y spec originales completos')
        for uid,spec,good in [('original',{},True),('recreated',{},False),('original',{'replicas':1},False)]:
            result=run_tasks([assertion],{'lab12_ha_uid':'original','lab12_orig_authorino':{},'lab12_ha_restored':{'resources':[{'metadata':{'uid':uid},'spec':spec}]}})
            self.assertEqual(result.returncode==0,good,result.stdout+result.stderr)
    def test_envoy_parser_and_counter_delta(self):
        tasks=yaml.safe_load((ROOT/'automation/labs/lab12/roles/lab12/tasks/authorino_ha_envoy.yml').read_text())[1:]
        assertion=task('Exigir 300 consultas adicionales al servicio de autorización')
        for value,good in [(1012,True),(1011,False)]:
            output=f"other-cluster::host::rq_total::9000\nkuadrant-auth-service::172.30.1.2:50051::rq_total::{value}\nkuadrant-auth-service::172.30.1.2:50051::cx_total::7\n"
            result=run_tasks(tasks+[assertion],{'lab12_ha_envoy_raw':{'stdout':output},'lab12_ha_envoy_baseline':{'rq_total':712}})
            self.assertEqual(result.returncode==0,good,result.stdout+result.stderr)

    def test_real_include_role_keeps_outer_response_separate(self):
        include=task('Validar contenido de cada 200 ya recibido sin generar más tráfico')
        common=yaml.safe_load((ROOT/'automation/common/roles/comun/defaults/main.yml').read_text())
        good={'status':200,'content_type':'application/json','json':{'Data':{'Party':{'PartyId':'CL-BANK-DEMO','name':'Backend de demo via Connectivity Link'}}}}
        for rows,expected in [([good]*5,True),([dict(good,json={'Data':{}})],False)]:
            result=run_tasks([include],{'lab12_ha_workload':{'results':rows},'wk_bank_json_contract':common['wk_bank_json_contract']})
            self.assertEqual(result.returncode==0,expected,result.stdout+result.stderr)
            self.assertNotIn('loop variable',result.stderr)

    def test_cached_json_uses_canonical_validator(self):
        validator=yaml.safe_load((ROOT/'automation/common/roles/comun/tasks/validar_http_contrato.yml').read_text())
        common=yaml.safe_load((ROOT/'automation/common/roles/comun/defaults/main.yml').read_text())
        for body,good in [({'Data':{'Party':{'PartyId':'CL-BANK-DEMO','name':'Backend de demo via Connectivity Link'}}},True),({'Data':{'Party':{'PartyId':'wrong'}}},False),(None,False)]:
            response={'content_type':'application/json'}
            if body is not None:response['json']=body
            result=run_tasks(validator,{'comun_http':response,'http_json_contract':common['wk_bank_json_contract']})
            self.assertEqual(result.returncode==0,good,result.stdout+result.stderr)
if __name__=='__main__':unittest.main()
