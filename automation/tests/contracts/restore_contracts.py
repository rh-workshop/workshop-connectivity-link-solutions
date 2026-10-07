"""Predicados TLS/restauración con fixtures Ansible, sin red ni mutaciones."""
import copy
from pathlib import Path
import unittest
import yaml
from common_roles import run_tasks

ROOT=Path(__file__).resolve().parents[3]/'automation/labs'
def tasks(lab,name):return yaml.safe_load((ROOT/lab/'roles'/lab/'tasks'/name).read_text())

class Restore(unittest.TestCase):
    def test_tls_refs(self):
        task=next(t for t in tasks('lab03','validar.yml') if 'ansible.builtin.assert' in t)
        original={'results':[{'resources':[{'spec':{'listeners':[{'name':'https','tls':{'certificateRefs':[{'name':'gw-tls'}]}}]},'status':{'addresses':[{'value':'lb'}]}}]},
                             {'resources':[{'metadata':{'name':'gw-tls'},'type':'kubernetes.io/tls'}]},
                             {'resources':[{'spec':{'secretName':'gw-tls'}}]}]}
        for case in ['valid','cert-secret','listener-secret','namespace','kind','group']:
            data=copy.deepcopy(original);ref=data['results'][0]['resources'][0]['spec']['listeners'][0]['tls']['certificateRefs'][0]
            if case=='cert-secret':data['results'][2]['resources'][0]['spec']['secretName']='other'
            if case=='listener-secret':ref['name']='other'
            if case in ['namespace','kind','group']:ref[case]='foreign'
            result=run_tasks([task],{'lab03_recursos':data,'entrada_modo':'loadbalancer','wk_gateway':'gw','wk_ns_gateway':'gateway-demo'})
            self.assertEqual(result.returncode==0,case=='valid',result.stdout+result.stderr)

    def test_preserved_policy(self):
        task=tasks('lab06','limpiar.yml')[-1]
        original={'metadata':{'uid':'original'},'spec':{'limits':{'per-user-per-minute':{'rates':[{'limit':5,'window':'60s'}]}}}}
        for case in ['valid','missing','recreated','changed','incomplete-revert']:
            before=copy.deepcopy(original);after=copy.deepcopy(original)
            if case=='recreated':after['metadata']['uid']='replacement'
            if case=='changed':after['spec']['limits']['per-user-per-minute']['rates'][0]['limit']=20
            if case=='incomplete-revert':
                before['spec']['limits']['per-user-per-minute']['rates'][0]['limit']=20
                after=copy.deepcopy(before)
            values={'lab06_cleanup_rlp_before':{'resources':[before]},'lab06_cleanup_rlp_after':{'resources':[] if case=='missing' else [after]},'lab06_ejercicio':True,'lab06_git_modo':'local','lab06_git_push':False,'lab06_limite_base':5}
            result=run_tasks([task],values)
            self.assertEqual(result.returncode==0,case=='valid',result.stdout+result.stderr)

    def test_readback_and_shared_contract(self):
        task=next(t for t in tasks('lab06','limpiar.yml') if t['name'].startswith('Esperar lectura'))
        for labels,success in [({},True),({'argocd.argoproj.io/managed-by':'openshift-gitops'},False)]:
            mocked=copy.deepcopy(task);mocked.pop('kubernetes.core.k8s_info');mocked.pop('register');mocked.pop('when')
            mocked['ansible.builtin.set_fact']={'lab06_cleanup_namespace':{'resources':[{'metadata':{'labels':labels}}]}}
            mocked['retries']=1;mocked['delay']=0
            result=run_tasks([mocked],{'lab06_sync_reintentos':1})
            self.assertEqual(result.returncode==0,success,result.stdout+result.stderr)
        rbac=next(t for t in tasks('lab06','limpiar.yml') if t['name'].startswith('Esperar a que el operador'))
        self.assertEqual(rbac['ansible.builtin.include_role']['tasks_from'],'esperar_borrado')
        self.assertEqual(rbac['loop'],['Role','RoleBinding'])
        restore=tasks('lab04b','restaurar.yml')[-1]['always'][-1]['block'][-1]
        bank=next(t for t in tasks('lab08','validar.yml') if t['name'].startswith('Registrar propiedad'))['block'][-1]
        self.assertEqual(restore['vars']['http_json_contract'],'{{ wk_bank_json_contract }}')
        self.assertEqual(bank['vars']['http_json_contract'],'{{ wk_bank_json_contract }}')

    def test_summary_requires_executed_steps(self):
        task=copy.deepcopy(tasks('lab06','validar.yml')[-1])
        task['ansible.builtin.debug']['msg']=[task['ansible.builtin.debug']['msg'][1]]
        for evidence,expected in [({},'no comprobados en esta ejecución'),({'self_heal':True},'commit/revert no comprobados'),({'self_heal':True,'change_commit':'a'*40,'revert_commit':'b'*40},'Commit y revert aplicados por SHA')]:
            result=run_tasks([task],{'lab06_exercise_evidence':evidence})
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)
            self.assertIn(expected,result.stdout)

if __name__=='__main__':unittest.main()
