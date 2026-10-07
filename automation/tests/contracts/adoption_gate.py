"""Regresiones offline: SSA impersonado, deriva real, identidad y evidencia privada."""
import copy
import base64
import importlib.util
import json
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import yaml

ROOT = Path(__file__).resolve().parents[3]
SPEC = importlib.util.spec_from_file_location('adoption', ROOT/'automation/scripts/check_adoption.py')
G = importlib.util.module_from_spec(SPEC); SPEC.loader.exec_module(G)
import git_source_proof as SOURCE


def pvc():
    return {'apiVersion':'v1','kind':'PersistentVolumeClaim','metadata':{'name':'database','namespace':'keycloak',
            'annotations':{'argocd.argoproj.io/sync-options':'Prune=false,Delete=false'},
            'labels':{'app':'database'}}, 'spec':{'accessModes':['ReadWriteOnce'],
            'resources':{'requests':{'storage':'50Gi'}},'storageClassName':'gp3'}}


def externals():
    return [
        {'apiVersion':'cert-manager.io/v1','kind':'ClusterIssuer','metadata':{'name':'letsencrypt-dns01','uid':'issuer-uid'},
         'spec':{'acme':{'server':'https://acme-v02.api.letsencrypt.org/directory','solvers':[{'dns01':{'route53':{'region':'us-east-1'}}}]}},
         'status':{'conditions':[{'type':'Ready','status':'True'}]}},
        {'apiVersion':'operator.openshift.io/v1alpha1','kind':'CertManager','metadata':{'name':'cluster','uid':'cm-uid'},
         'spec':{'controllerConfig':{'overrideArgs':['--dns01-recursive-nameservers-only','--dns01-recursive-nameservers=8.8.8.8:53']},
                 'unknownVendorConfig':{'keep':True}}},
        {'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'cluster-monitoring-config','namespace':'openshift-monitoring','uid':'uwm-uid'},
         'data':{'config.yaml':'enableUserWorkload: true\notherConfig: retained\n'}},
    ]


def tracking():
    return {'apiVersion':'v1','kind':'ConfigMap', 'metadata':{'name':G.IDENTITY['name']+'-cm','namespace':G.IDENTITY['namespace'],'uid':'tracking-uid'},
            'data':{'resource.respectRBAC':'normal','application.resourceTrackingMethod':'annotation','application.instanceLabelKey':'app.kubernetes.io/instance'}}



def cluster_configuration(namespaces=()):
    public={'name':G.IDENTITY['name']+'-default-cluster','server':'https://kubernetes.default.svc',
            'namespaces':','.join(sorted(set(namespaces)|{G.IDENTITY['namespace']})),'clusterResources':'true',
            'config':'{"bearerToken":"DO-NOT-EXPORT-TOKEN","tlsClientConfig":{"insecure":false}}'}
    return {'apiVersion':'v1','kind':'Secret','type':'Opaque','metadata':{'name':G.IDENTITY['name']+'-default-cluster-config','namespace':G.IDENTITY['namespace'],'uid':'configuration-uid','labels':{'argocd.argoproj.io/secret-type':'cluster'},'ownerReferences':[{'apiVersion':'argoproj.io/v1beta1','kind':'ArgoCD','name':G.IDENTITY['name'],'uid':'argo-uid'}]},'data':{k:base64.b64encode(v.encode()).decode() for k,v in public.items()}}


class Fake:
    def __init__(self):
        self.live = pvc(); self.live['metadata'].update(uid='pvc-uid', resourceVersion='11')
        self.live['spec']['unknownVendorConfig'] = {'preserved':True}
        self.external = {G.key(r):r for r in externals()}
        self.external[G.key(tracking())] = tracking()
        self.configuration=cluster_configuration()
        self.configuration_change_after_ssa=None
        self.change = None; self.calls = []; self.payloads = []; self.denied = False; self.missing = False
    def get(self, resource, impersonate=True):
        self.calls.append(('get', impersonate))
        if resource['kind']=='Secret':return copy.deepcopy(self.configuration)
        if resource['kind']=='ArgoCD':return G.reference(resource)|{'metadata':resource['metadata']|{'uid':'argo-uid'},'spec':{'controller':{'respectRBAC':'normal'}}}
        if resource['metadata']['name'] == 'kube-system': return {'metadata':{'uid':'cluster-uid'}}
        if resource['kind']=='ServiceAccount' and resource['metadata']['namespace']==G.IDENTITY['namespace']:
            return G.reference(resource)|{'metadata':resource['metadata']|{'uid':'controller-uid'}}
        if not impersonate: return copy.deepcopy(self.external[G.key(resource)])
        if self.missing: raise ValueError('missing_resource')
        return copy.deepcopy(self.live)
    def role_bindings(self,namespace):return []
    def can_i(self,verb,resource,namespace=None):
        return False
    def remote_reference(self, contract):
        return contract['revision']
    def dry_run(self, resource):
        self.calls.append(('dry_run', True))
        self.payloads.append(copy.deepcopy(resource))
        if self.denied: raise ValueError('access_denied')
        result = copy.deepcopy(self.live)
        result['metadata']['resourceVersion'] = '12'
        result['status'] = {'phase':'Bound'}
        if self.change: self.change(result)
        if self.configuration_change_after_ssa:self.configuration_change_after_ssa(self.configuration)
        return result


class Adoption(unittest.TestCase):
    def fixture(self, folder, resource=None):
        resource = resource or pvc()
        target=folder/'components/keycloak'; target.mkdir(parents=True)
        (target/'manifests.yaml').write_text(yaml.safe_dump(resource))
        (folder/'handoff-blockers.json').write_text('[]')
        (folder/'adoption-map.json').write_text(json.dumps([{'apiVersion':resource['apiVersion'],'kind':resource['kind'],**resource['metadata'],'phase':'keycloak'}]))
        (target/'kustomization.yaml').write_text(yaml.safe_dump({'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization','resources':['manifests.yaml']}))
        export=folder/'export/platform/components/keycloak'
        shutil.copytree(target,export)
        bundle=folder/'source.bundle'; SOURCE.P.create_bundle(folder/'export',bundle)
        revision=SOURCE.run(['git','bundle','list-heads',str(bundle),'refs/heads/main']).split()[0]
        (folder/'applications').mkdir()
        (folder/'applications/keycloak.yaml').write_text(yaml.safe_dump({'apiVersion':'argoproj.io/v1alpha1','kind':'Application',
            'metadata':{'name':'cl-platform-keycloak','namespace':G.IDENTITY['namespace']},'spec':{'project':'cl-platform','destination':{'server':'https://kubernetes.default.svc'},
            'source':{'targetRevision':revision,'repoURL':SOURCE.INTERNAL_REPO,'path':'platform/components/keycloak'},
            'syncPolicy':{'syncOptions':['ServerSideApply=true','ClientSideApplyMigration=false','FailOnSharedResource=true']}}}))
        (folder/'external-preconditions.json').write_text(json.dumps([{'apiVersion':r['apiVersion'],'kind':r['kind'],**r['metadata']} for r in externals()]))
        return {'cluster_configuration':G.cluster_configuration_snapshot(cluster_configuration(),'argo-uid'),'controller':{'identity':copy.deepcopy(G.IDENTITY),'uid':'controller-uid'},'cluster_uid':'cluster-uid','bundle_sha256':G.digest([resource]),
                'applications_sha256':G.applications_digest(folder),
                'git_source':{'bundle':str(bundle),'revision':revision,'repo_url':SOURCE.INTERNAL_REPO,'published_path':'platform'},
                'tracking_config':{'apiVersion':'v1','kind':'ConfigMap','metadata':tracking()['metadata'],
                                   'uid':'tracking-uid','data':tracking()['data']},
                'resources':{G.key(resource):'pvc-uid'},'external':{G.key(r):{'uid':r['metadata']['uid'],
                'functional':G.external_functional(r)} for r in externals()}}

    def test_effective_normal_cache_mode_required_in_cr_and_configmap(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder);client=Fake()
            client.external[G.key(tracking())]['data']['resource.respectRBAC']='strict'
            expected['tracking_config']['data']['resource.respectRBAC']='strict'
            with self.assertRaisesRegex(ValueError,'cache_rbac_mode_not_normal'):G.audit(folder,expected,client)
            expected['tracking_config']['data']['resource.respectRBAC']='normal'
            client=Fake();getter=client.get
            def get(resource,impersonate=True):
                result=getter(resource,impersonate)
                if resource['kind']=='ArgoCD':result['spec']['controller']['respectRBAC']='strict'
                return result
            client.get=get
            with self.assertRaisesRegex(ValueError,'cache_cr_mode_not_normal'):G.audit(folder,expected,client)

    def test_cluster_configuration_scope_owner_and_credentials_hash_fail_closed(self):
        mutations=[lambda s:s['metadata'].update(uid='other'),
                   lambda s:s['metadata']['ownerReferences'][0].update(uid='wrong-argo'),
                   lambda s:s['data'].update(server=base64.b64encode(b'https://other.cluster').decode()),
                   lambda s:s['data'].update(name=base64.b64encode(b'other-cluster').decode()),
                   lambda s:s['data'].update(namespaces=base64.b64encode(b'cl-platform-argocd,kube-system').decode()),
                   lambda s:s['data'].update(clusterResources=base64.b64encode(b'false').decode()),
                   lambda s:s['data'].update(config=base64.b64encode(b'CHANGED-PRIVATE-CREDENTIALS').decode())]
        for change in mutations:
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);expected=self.fixture(folder);client=Fake();change(client.configuration)
                with self.assertRaises(ValueError):G.audit(folder,expected,client)
                self.assertNotIn(('dry_run',True),client.calls)
        contract=G.cluster_configuration_snapshot(cluster_configuration(),'argo-uid')
        self.assertNotIn('DO-NOT-EXPORT-TOKEN',json.dumps(contract));self.assertNotIn('config',contract)
        self.assertEqual(len(contract['other_data_sha256']),64)

    def test_cluster_configuration_missing_guard_and_change_after_ssa_abort(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder);bad=copy.deepcopy(expected);bad.pop('cluster_configuration')
            with self.assertRaisesRegex(ValueError,'missing_cluster_configuration_guard'):G.audit(folder,bad,Fake())
            client=Fake();client.configuration_change_after_ssa=lambda s:s['data'].update(config=base64.b64encode(b'NEW-TOKEN').decode())
            with self.assertRaisesRegex(ValueError,'cluster_configuration_snapshot_drift'):G.audit(folder,expected,client)
            self.assertIn(('dry_run',True),client.calls)

    def test_tokenrequest_negative_probe_uses_real_subresource_not_resource_name(self):
        commands=[]
        def run(command,**kwargs):
            commands.append(command)
            return type('Result',(),{'returncode':1,'stdout':'no\n','stderr':''})()
        with patch.object(G.subprocess,'run',run):
            self.assertFalse(G.Oc().can_i('create','serviceaccounts/token','keycloak'))
            self.assertFalse(G.Oc().can_i('create','subjectaccessreviews.authorization.k8s.io'))
        self.assertIn('--subresource=token',commands[0]);self.assertNotIn('serviceaccounts/token',commands[0])
        self.assertEqual(commands[0][-4:],['serviceaccounts','--subresource=token','-n','keycloak'])
        self.assertIn('subjectaccessreviews.authorization.k8s.io',commands[1])

    def test_rolebinding_collection_actual_oc_list_and_strict_scope(self):
        binding={'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':{'name':'reader','namespace':'tempo'}}
        for kind in ['List','RoleBindingList']:
            with patch.object(G.Oc,'run',return_value={'kind':kind,'items':[binding]}):
                self.assertEqual(G.Oc().role_bindings('tempo'),[binding])
        with patch.object(G.Oc,'run',return_value={'kind':'List','items':[]}):
            self.assertEqual(G.Oc().role_bindings('tempo'),[])
        binding['metadata']['namespace']='keycloak'
        with patch.object(G.Oc,'run',return_value={'kind':'List','items':[binding]}):
            with self.assertRaisesRegex(ValueError,'rolebinding_identity_mismatch'):G.Oc().role_bindings('tempo')

    def test_external_namespace_full_snapshot_active_labels_and_admin_bindings(self):
        namespace={'apiVersion':'v1','kind':'Namespace','metadata':{'name':'tempo','uid':'ns-uid','labels':{'original':'retained'}},'spec':{'finalizers':['kubernetes']},'status':{'phase':'Active'}}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder);client=Fake();identity=G.key(namespace)
            client.external[identity]=copy.deepcopy(namespace)
            descriptors=json.loads((folder/'external-preconditions.json').read_text());descriptors.append({'apiVersion':'v1','kind':'Namespace','name':'tempo'})
            (folder/'external-preconditions.json').write_text(json.dumps(descriptors))
            expected['external'][identity]={'uid':'ns-uid','functional':G.external_functional(namespace)}
            client.configuration=cluster_configuration(['tempo'])
            expected['cluster_configuration']=G.cluster_configuration_snapshot(client.configuration,'argo-uid')
            report=G.audit(folder,expected,client);self.assertTrue(report['ok'])
            self.assertTrue(all(not p['allowed'] for p in report['negative_permission_baseline']))
            self.assertIn({'verb':'update','resource':'namespaces/tempo','namespace':None,'allowed':False},report['negative_permission_baseline'])
            client.can_i=lambda verb,resource,ns:verb=='update' and resource=='namespaces/tempo'
            with self.assertRaisesRegex(ValueError,'effective_rbac_not_restricted'):G.audit(folder,expected,client)
            client.can_i=lambda *args:False
            client.external[identity]['spec']['finalizers']=[]
            self.assertFalse(G.audit(folder,expected,client)['ok'])
            client.external[identity]=copy.deepcopy(namespace);client.external[identity]['status']['phase']='Terminating'
            self.assertFalse(G.audit(folder,expected,client)['ok'])
            for label in ['argocd.argoproj.io/managed-by','argocd.argoproj.io/managed-by-cluster-argocd']:
                client.external[identity]=copy.deepcopy(namespace);client.external[identity]['metadata']['labels'][label]=G.IDENTITY['namespace']
                expected['external'][identity]['functional']=G.external_functional(client.external[identity])
                report=G.audit(folder,expected,client);self.assertFalse(report['ok']);self.assertIn('external_namespace_managed_by_platform_controller',report['records'][-1]['errors'])
            client.external[identity]=copy.deepcopy(namespace);expected['external'][identity]['functional']=G.external_functional(namespace)
            client.role_bindings=lambda ns:[{'roleRef':{'kind':'ClusterRole','name':'admin'},'subjects':[{'kind':'ServiceAccount','name':G.IDENTITY['service_account'],'namespace':G.IDENTITY['namespace']}]}]
            report=G.audit(folder,expected,client);self.assertFalse(report['ok']);self.assertIn('external_namespace_admin_binding_to_platform_controller',report['records'][-1]['errors'])
            self.assertFalse(any(p['kind']=='Namespace' for p in client.payloads))

    def test_controller_identity_uid_and_effective_negative_permissions_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder)
            for permission in [('bind','clusterroles/cl-platform-argocd',None),('patch','namespaces/kube-system',None),('create','serviceaccounts/token','keycloak'),('create','subjectaccessreviews.authorization.k8s.io',None)]:
                client=Fake();client.can_i=lambda *args:args==permission
                with self.assertRaisesRegex(ValueError,'effective_rbac_not_restricted'):G.audit(folder,expected,client)
                self.assertNotIn(('dry_run',True),client.calls)
            bad=copy.deepcopy(expected);bad['controller']['identity']['namespace']='openshift-gitops'
            with self.assertRaisesRegex(ValueError,'controller_guard'):G.audit(folder,bad,Fake())
            bad=copy.deepcopy(expected);bad['controller']['uid']='wrong'
            with self.assertRaisesRegex(ValueError,'controller_uid_mismatch'):G.audit(folder,bad,Fake())

    def test_rbac_external_full_rules_and_binding_contract_abort_before_ssa(self):
        for resource in [
            {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRole','metadata':{'name':'participant','uid':'role-uid'},'rules':[{'apiGroups':[''],'resources':['pods'],'verbs':['get']}]},
            {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding','metadata':{'name':'reader','namespace':'tempo','uid':'binding-uid'},'subjects':[{'kind':'User','name':'participant'}],'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'participant'}}]:
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);expected=self.fixture(folder);client=Fake()
                key=G.key(resource);client.external[key]=copy.deepcopy(resource)
                descriptors=json.loads((folder/'external-preconditions.json').read_text())
                descriptors.append({'apiVersion':resource['apiVersion'],'kind':resource['kind'],**{k:resource['metadata'][k] for k in ('name','namespace') if k in resource['metadata']},'canonical':resource})
                (folder/'external-preconditions.json').write_text(json.dumps(descriptors))
                expected['external'][key]={'uid':resource['metadata']['uid'],'functional':G.external_functional(resource)}
                self.assertTrue(G.audit(folder,expected,client)['ok'])
                if resource['kind']=='ClusterRole':client.external[key]['rules'][0]['verbs'].append('delete')
                else:client.external[key]['roleRef']['name']='admin'
                # Incluso un snapshot que acepta el cambio no puede aprobar deriva de la fuente canónica.
                expected['external'][key]['functional']=G.external_functional(client.external[key])
                client.calls=[]
                report=G.audit(folder,expected,client)
                self.assertFalse(report['ok']);self.assertNotIn(('dry_run',True),client.calls)
                self.assertIn('external_rbac_canonical_drift',report['records'][-1]['errors'])

    def test_api_normalized_defaults_and_volatile_fields_pass(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder);client=Fake()
            report=G.audit(folder,expected,client)
            self.assertTrue(report['ok'],report)
            self.assertIn(('dry_run',True),client.calls)
            self.assertEqual(client.payloads[0]['metadata']['annotations']['argocd.argoproj.io/tracking-id'],
                             'cl-platform-keycloak:/PersistentVolumeClaim:keycloak/database')
            self.assertNotIn('app.kubernetes.io/instance',client.payloads[0]['metadata']['labels'])
            self.assertNotIn('50Gi',json.dumps(report))

    def test_storage_unknown_config_and_functional_metadata_drift_rejected(self):
        mutations=[lambda r:r['spec']['resources']['requests'].update(storage='30Gi'),
                   lambda r:r['spec'].pop('unknownVendorConfig'),
                   lambda r:r['metadata']['labels'].update(app='other'),
                   lambda r:r['metadata'].setdefault('annotations',{}).update({'functional.vendor/setting':'changed'})]
        for mutation in mutations:
            with self.subTest(mutation=mutation),tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);expected=self.fixture(folder);client=Fake();client.change=mutation
                report=G.audit(folder,expected,client)
                self.assertFalse(report['ok'])
                self.assertIn('functional_drift',report['records'][-1]['errors'])
                self.assertTrue(report['records'][-1]['changed_fields'])

    def test_external_wrong_issuer_unknown_config_and_monitoring_abort_before_ssa(self):
        for index in range(3):
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);expected=self.fixture(folder);client=Fake();resource=list(client.external.values())[index]
                if index==0: resource['spec']['acme']['server']='https://staging.invalid/directory'
                elif index==1: resource['spec']['unknownVendorConfig']={'keep':False}
                else: resource['data']['config.yaml']='enableUserWorkload: false'
                report=G.audit(folder,expected,client)
                self.assertFalse(report['ok']);self.assertNotIn(('dry_run',True),client.calls)

    def test_bad_external_configuration_cannot_be_approved_by_snapshot_alone(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder);client=Fake()
            issuer=client.external[G.key(externals()[0])]
            issuer['spec']['acme']['server']='https://staging.invalid/directory'
            expected['external'][G.key(issuer)]['functional']['spec']=copy.deepcopy(issuer['spec'])
            report=G.audit(folder,expected,client)
            self.assertFalse(report['ok'])
            self.assertEqual(report['records'][0]['errors'],['external_issuer_wrong_configuration'])
            self.assertNotIn(('dry_run',True),client.calls)

    def test_access_denied_missing_and_changed_uid_are_not_success(self):
        for failure in ['denied','missing','uid']:
            with tempfile.TemporaryDirectory() as tmp:
                folder=Path(tmp);expected=self.fixture(folder);client=Fake()
                if failure=='uid': client.live['metadata']['uid']='different'
                else:setattr(client,failure,True)
                self.assertFalse(G.audit(folder,expected,client)['ok'])

    def test_guard_digest_cluster_uid_and_secret_fail_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder)
            for field,value in [('cluster_uid','other'),('bundle_sha256','0'*64),('resources',{})]:
                bad=copy.deepcopy(expected);bad[field]=value
                with self.assertRaises(ValueError):G.audit(folder,bad,Fake())
            secret=pvc();secret['kind']='Secret';secret['data']={'credential':'NEVER-PRINT'}
            (folder/'components/keycloak/manifests.yaml').write_text(yaml.safe_dump(secret))
            with self.assertRaisesRegex(ValueError,'secret_or_list'):G.desired(folder)
            namespace={'apiVersion':'v1','kind':'Namespace','metadata':{'name':'tempo','annotations':{'argocd.argoproj.io/sync-options':'Prune=false,Delete=false'}}}
            (folder/'components/keycloak/manifests.yaml').write_text(yaml.safe_dump(namespace))
            with self.assertRaisesRegex(ValueError,'secret_or_list'):G.desired(folder)

    def test_real_oc_command_contract_only_dry_run_and_exact_sa_groups(self):
        commands=[]
        def run(command,**kwargs):
            commands.append(command)
            return type('Result',(),{'returncode':0,'stdout':kwargs['input'],'stderr':''})()
        with patch.object(G.subprocess,'run',run):G.Oc().dry_run(pvc())
        command=commands[0]
        for flag in ['--as='+G.SA,'--dry-run=server','--server-side','--force-conflicts','--field-manager=argocd-controller']:
            self.assertIn(flag,command)
        for group in G.GROUPS:self.assertIn('--as-group='+group,command)
        self.assertNotIn('replace',command)

    def test_oc_list_envelope_requires_one_exact_identity(self):
        resource=pvc();resource['metadata']['uid']='actual-uid'
        with patch.object(G.Oc,'run',return_value={'apiVersion':'v1','kind':'List','items':[resource]}):
            self.assertEqual(G.Oc().get(pvc())['metadata']['uid'],'actual-uid')
            self.assertEqual(G.Oc().dry_run(pvc())['kind'],'PersistentVolumeClaim')
        wrong=copy.deepcopy(resource);wrong['metadata']['namespace']='another-namespace'
        for items, code in [([], 'missing_resource'),([resource,resource],'ambiguous_api_list'),
                            ([wrong],'api_identity_mismatch')]:
            with self.subTest(items=len(items)),patch.object(G.Oc,'run',return_value={'kind':'List','items':items}):
                with self.assertRaisesRegex(ValueError,code):G.Oc().get(pvc())

    def test_private_report_no_overwrite_and_outside_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);path=folder/'report.json'
            G.private_report(path,{'ok':True})
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):G.private_report(path,{'ok':False})
            (folder/'.git').mkdir()
            with self.assertRaisesRegex(ValueError,'outside_git'):G.private_report(folder/'other.json',{})

    def test_foreign_tracking_is_not_ignored(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder);client=Fake()
            client.live['metadata']['annotations']['argocd.argoproj.io/tracking-id']='other-app:v1/PersistentVolumeClaim:keycloak/database'
            self.assertFalse(G.audit(folder,expected,client)['ok'])

    def test_unproven_tracking_method_blocked_and_functional_instance_label_compared(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder);client=Fake()
            for method in ['label','annotation+label','']:
                client.external[G.key(tracking())]['data']['application.resourceTrackingMethod']=method
                expected['tracking_config']['data']['application.resourceTrackingMethod']=method
                with self.assertRaisesRegex(ValueError,'tracking_method_not_proven'):G.audit(folder,expected,client)
            client.external[G.key(tracking())]=tracking();expected['tracking_config']['data']=tracking()['data']
            client.change=lambda r:r['metadata']['labels'].update({'app.kubernetes.io/instance':'different'})
            report=G.audit(folder,expected,client)
            self.assertFalse(report['ok'])
            self.assertIn('$.metadata.labels.app.kubernetes.io/instance',report['records'][-1]['changed_fields'])

    def test_wrong_certificate_issuer_and_zero_revision_rejected(self):
        certificate = {'apiVersion':'cert-manager.io/v1','kind':'Certificate',
            'metadata':{'name':'router','namespace':'openshift-ingress',
                        'annotations':{'argocd.argoproj.io/sync-options':'Prune=false,Delete=false'}},
            'spec':{'dnsNames':['*.apps.cluster.example.com'],'secretName':'router-tls',
                    'issuerRef':{'kind':'Issuer','name':'cl-ingress-acme'}}}
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);expected=self.fixture(folder,certificate);client=Fake()
            client.live=copy.deepcopy(certificate);client.live['metadata']['uid']='pvc-uid'
            client.change=lambda r:r['spec']['issuerRef'].update(name='wrong-issuer')
            report=G.audit(folder,expected,client)
            self.assertFalse(report['ok'])
            self.assertIn('$.spec.issuerRef.name',report['records'][-1]['changed_fields'])
            app=folder/'applications/keycloak.yaml';source=yaml.safe_load(app.read_text())
            source['spec']['source']['targetRevision']='0'*40;app.write_text(yaml.safe_dump(source))
            with self.assertRaisesRegex(ValueError,'invalid_application_revision'):G.desired(folder)


if __name__=='__main__':unittest.main()
