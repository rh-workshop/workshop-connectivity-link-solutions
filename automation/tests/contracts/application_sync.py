"""Una aplicación sana previa no acredita una nueva operación de adopción."""
import copy
import importlib.util
from pathlib import Path
import unittest

ROOT=Path(__file__).resolve().parents[3]
spec=importlib.util.spec_from_file_location('application_sync_gate',ROOT/'automation/scripts/check_application_sync.py')
M=importlib.util.module_from_spec(spec);spec.loader.exec_module(M)
SHA='a'*40;NONCE='validation-unique-123';NAME=M.G.IDENTITY['name']+'-operators'


def fixture():
    resource={'apiVersion':'operators.coreos.com/v1alpha1','kind':'Subscription','metadata':{'name':'operator-a','namespace':'openshift-operators'}}
    record={'group':'operators.coreos.com','kind':'Subscription','namespace':'openshift-operators','name':'operator-a','status':'Synced'}
    application={'apiVersion':'argoproj.io/v1alpha1','kind':'Application','metadata':{'name':NAME,'namespace':M.G.IDENTITY['namespace'],'uid':'existing-app-uid'},
                 'spec':{'source':{'targetRevision':SHA}},'status':{'sync':{'status':'Synced','revision':SHA},'resources':[copy.deepcopy(record)],
                 'operationState':{'phase':'Succeeded','operation':{'info':[{'name':'validation-run','value':NONCE}],'sync':{'revision':SHA,'prune':False}},
                                   'syncResult':{'revision':SHA,'resources':[record]}}}}
    return application,[resource]


class Sync(unittest.TestCase):
    def check(self,application,resources):return M.validate(application,resources,SHA,NONCE,NAME)
    def test_exact_operation_and_both_resource_sets_pass(self):
        a,r=fixture();report=self.check(a,r);self.assertTrue(report['ok']);self.assertEqual(report['resource_count'],1)
    def test_stale_operation_cannot_pass_despite_synced_healthy_status(self):
        a,r=fixture();a['status']['health']={'status':'Healthy'};a['status']['operationState']['operation']['info'][0]['value']='older-run'
        with self.assertRaisesRegex(ValueError,'operation_id_mismatch'):self.check(a,r)
    def test_wrong_revision_at_each_layer_is_rejected(self):
        for path in [('spec','source','targetRevision'),('status','sync','revision'),('status','operationState','syncResult','revision'),('status','operationState','operation','sync','revision')]:
            a,r=fixture();target=a
            for key in path[:-1]:target=target[key]
            target[path[-1]]='b'*40
            with self.subTest(path=path),self.assertRaises(ValueError):self.check(a,r)
    def test_subset_extra_duplicate_wrong_gvk_or_pruned_resources_fail(self):
        for which in ('result','status'):
            for mutation in ('empty','extra','duplicate','wrong_kind','wrong_namespace','wrong_version','pruned'):
                a,r=fixture();records=a['status']['operationState']['syncResult']['resources'] if which=='result' else a['status']['resources']
                if mutation=='empty':records.clear()
                elif mutation=='extra':records.append(records[0]|{'name':'unrequested'})
                elif mutation=='duplicate':records.append(copy.deepcopy(records[0]))
                elif mutation=='wrong_kind':records[0]['kind']='OperatorGroup'
                elif mutation=='wrong_namespace':records[0]['namespace']='keycloak'
                elif mutation=='wrong_version':records[0]['version']='v99'
                else:records[0]['status']='Pruned'
                with self.subTest(which=which,mutation=mutation),self.assertRaises(ValueError):self.check(a,r)
    def test_active_automatic_finalized_error_or_failed_operation_rejected(self):
        for mutation in ('active','automated','finalizer','error','failed','prune','duplicate_nonce'):
            a,r=fixture()
            if mutation=='active':a['operation']={'sync':{'revision':SHA}}
            elif mutation=='automated':a['spec']['syncPolicy']={'automated':{}}
            elif mutation=='finalizer':a['metadata']['finalizers']=['resources-finalizer.argocd.argoproj.io']
            elif mutation=='error':a['status']['conditions']=[{'type':'ComparisonError','message':'DO-NOT-EXPORT'}]
            elif mutation=='failed':a['status']['operationState']['phase']='Failed'
            elif mutation=='prune':a['status']['operationState']['operation']['sync']['prune']=True
            else:a['status']['operationState']['operation']['info']*=2
            with self.subTest(mutation=mutation),self.assertRaises(ValueError):self.check(a,r)


if __name__=='__main__':unittest.main()
