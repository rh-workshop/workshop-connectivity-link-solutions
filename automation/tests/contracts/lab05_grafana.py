"""Predicados reales de CR Grafana; fixtures sin clúster ni credenciales."""
import copy
from pathlib import Path
import unittest
import yaml
from common_roles import run_tasks

ROOT=Path(__file__).resolve().parents[3]
TASKS=yaml.safe_load((ROOT/'automation/labs/lab05/roles/lab05/tasks/plataforma_verificar.yml').read_text())
BLOCK=next(t['block'] for t in TASKS if t['name'].startswith('Comprobar Grafana'))

class Grafana(unittest.TestCase):
    def test_dashboard_id_condition_and_generation(self):
        task=next(t for t in BLOCK if t['name'].startswith('Comprobar IDs'))
        original={'metadata':{'name':'rhcl-app-developer','generation':2},'spec':{'grafanaCom':{'id':21538}},
                  'status':{'conditions':[{'type':'DashboardSynchronized','status':'True','observedGeneration':2}]}}
        for case in ['valid','missing','wrong-id','false','stale']:
            resource=copy.deepcopy(original)
            if case=='wrong-id':resource['spec']['grafanaCom']['id']=999
            if case=='false':resource['status']['conditions'][0]['status']='False'
            if case=='stale':resource['status']['conditions'][0]['observedGeneration']=1
            values={'lab05_grafana_dashboards':{'rhcl-app-developer':21538},'lab05_dashboards':{'resources':[] if case=='missing' else [resource]}}
            result=run_tasks([task],values)
            self.assertEqual(result.returncode==0,case=='valid',result.stdout+result.stderr)

    def test_datasource_contract_condition_and_generation(self):
        task=next(t for t in BLOCK if t['name'].startswith('Comprobar contrato'))
        original={'metadata':{'generation':2},'spec':{'datasource':{'type':'prometheus','uid':'prometheus','access':'proxy','url':'https://thanos-querier.openshift-monitoring.svc.cluster.local:9091'}},
                  'status':{'conditions':[{'type':'DatasourceSynchronized','status':'True','observedGeneration':2}]}}
        for case in ['valid','missing','wrong-url','wrong-uid','false','stale']:
            resource=copy.deepcopy(original)
            if case=='wrong-url':resource['spec']['datasource']['url']='http://unrelated'
            if case=='wrong-uid':resource['spec']['datasource']['uid']='other'
            if case=='false':resource['status']['conditions'][0]['status']='False'
            if case=='stale':resource['status']['conditions'][0]['observedGeneration']=1
            result=run_tasks([task],{'lab05_datasource':{'resources':[] if case=='missing' else [resource]}})
            self.assertEqual(result.returncode==0,case=='valid',result.stdout+result.stderr)

if __name__=='__main__':unittest.main()
