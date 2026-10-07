"""Cache finito: negativos reales de permisos y LIST, nunca exportar cuerpos."""
import importlib.util
from pathlib import Path
import unittest
ROOT=Path(__file__).resolve().parents[3]
s=importlib.util.spec_from_file_location('cache_preflight',ROOT/'automation/scripts/check_cache_permissions.py');M=importlib.util.module_from_spec(s);s.loader.exec_module(M)


def resources():
    return [{'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'app','namespace':'keycloak'}}]


class Fake:
    def __init__(self):self.calls=[];self.denied=None;self.list_failure=False
    def can_i(self,verb,resource,namespace):
        self.calls.append(('can_i',verb,resource,namespace))
        return (verb,namespace)!=self.denied
    def run(self,args):
        self.calls.append(tuple(args));path=args[-1]
        if path=='/apis/apps/v1':return {'resources':[{'name':'deployments','kind':'Deployment','namespaced':True}]}
        if self.list_failure:raise ValueError('access_denied')
        namespace=path.split('/namespaces/')[1].split('/')[0]
        return {'apiVersion':'apps/v1','kind':'DeploymentList','items':[{'apiVersion':'apps/v1','kind':'Deployment','metadata':{'namespace':namespace,'name':'NEVER-REPORT-NAME','uid':'existing-uid'},'spec':{'envSecret':'NEVER-REPORT-VALUE'}}]}


class Cache(unittest.TestCase):
    def test_every_type_namespace_pair_can_list_watch_and_real_limited_list(self):
        fake=Fake();report=M.matrix(resources(),{'keycloak','tempo'},fake,workers=2)
        self.assertTrue(report['ok']);self.assertEqual(report['pair_count'],3)
        self.assertEqual(len([c for c in fake.calls if c[0]=='can_i']),6)
        lists=[c for c in fake.calls if c[0]=='get' and 'limit=1' in c[-1]];self.assertEqual(len(lists),3)
        self.assertNotIn('NEVER-REPORT',str(report));self.assertTrue(all(r['listed_count']==1 for r in report['records']))
    def test_missing_watch_or_real_list_denial_cannot_pass(self):
        fake=Fake();fake.denied=('watch','tempo');report=M.matrix(resources(),{'tempo'},fake)
        self.assertFalse(report['ok']);self.assertIn('cache_collection_permission_denied',report['records'][-1]['errors'])
        fake=Fake();fake.list_failure=True;self.assertFalse(M.matrix(resources(),{'tempo'},fake)['ok'])
    def test_timeout_and_wrong_collection_fail_without_item_output(self):
        fake=Fake(); original=fake.run
        def timeout(args):
            if 'limit=1' in args[-1]:raise M.G.subprocess.TimeoutExpired('oc',1,stderr='NEVER-REPORT-CREDENTIAL')
            return original(args)
        fake.run=timeout;report=M.matrix(resources(),{'tempo'},fake)
        self.assertFalse(report['ok']);self.assertNotIn('NEVER-REPORT',str(report))
        fake=Fake();original=fake.run
        def wrong(args):
            response=original(args)
            if 'limit=1' in args[-1]:response['items'][0]['metadata']['namespace']='other'
            return response
        fake.run=wrong;self.assertFalse(M.matrix(resources(),{'tempo'},fake)['ok'])
    def test_typed_list_supplies_omitted_item_gvk_but_rejects_explicit_wrong_identity(self):
        def report_with(change):
            fake=Fake();original=fake.run
            def response(args):
                result=original(args)
                if 'limit=1' in args[-1]:change(result)
                return result
            fake.run=response
            return M.matrix(resources(),{'tempo'},fake)
        def omit_gvk(result):
            result['items'][0].pop('apiVersion');result['items'][0].pop('kind')
        report=report_with(omit_gvk)
        self.assertTrue(report['ok']);self.assertNotIn('NEVER-REPORT',str(report))
        for change in (
            lambda d:d['items'][0].update(apiVersion='apps/v2'),
            lambda d:d['items'][0].update(kind='StatefulSet'),
            lambda d:d.update(apiVersion='apps/v2'),
            lambda d:d['items'][0]['metadata'].pop('uid'),
            lambda d:d['items'][0]['metadata'].pop('name'),
            lambda d:d['items'][0]['metadata'].update(namespace='other'),
        ):
            with self.subTest(change=change):self.assertFalse(report_with(change)['ok'])
        def generic_without_gvk(result):
            omit_gvk(result);result['kind']='List'
        self.assertFalse(report_with(generic_without_gvk)['ok'])
    def test_secret_external_types_and_wrong_discovery_are_rejected(self):
        for kind in ('Secret','Namespace','ClusterRole'):
            r=resources();r[0]['kind']=kind
            with self.assertRaisesRegex(ValueError,'sensitive_cache_kind'):M.matrix(r,{'tempo'},Fake())
        r=resources();r[0]['kind']='HorizontalPodAutoscaler'
        with self.assertRaisesRegex(ValueError,'discovery_mismatch'):M.matrix(r,{'tempo'},Fake())
        with self.assertRaisesRegex(ValueError,'namespace_invalid'):M.matrix(resources(),{'*'},Fake())


if __name__=='__main__':unittest.main()
