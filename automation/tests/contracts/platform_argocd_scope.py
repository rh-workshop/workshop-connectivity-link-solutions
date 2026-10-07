"""Scope de conexión existente: CAS, respaldo mínimo y guardias sin clúster."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
import yaml
from participant_access import apply_patch, ansible_python

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT/'automation/common/roles/platform_argocd'
SPEC = importlib.util.spec_from_file_location('platform_scope', ROLE/'library/platform_argocd_scope.py')
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def encoded(value):
    return base64.b64encode(value.encode()).decode()


class PlatformScope(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root/'external-preconditions.json').write_text(json.dumps([
            {'apiVersion':'v1','kind':'Namespace','name':'platform-'+str(i)} for i in range(13)]))
        self.identity=yaml.safe_load((ROOT/'automation/common/platform-argocd.yml').read_text())
        self.secret={'metadata':{'name':self.identity['name']+'-default-cluster-config',
            'namespace':self.identity['namespace'],'uid':'secret-uid','resourceVersion':'17',
            'ownerReferences':[{'apiVersion':'argoproj.io/v1beta1','kind':'ArgoCD',
                'name':self.identity['name'],'uid':'instance-uid'}]},
            'data':{'server':encoded('https://kubernetes.default.svc'),
                    'config':encoded('fixture-private-credential'), 'name':encoded('local-name')}}
        self.args={'operation':'plan','identity':self.identity,'instance_uid':'instance-uid',
            'expected_secret_uid':'secret-uid','secrets':[self.secret],'applications':[],
            'render_dir':str(self.root), 'namespaces':['platform-'+str(i) for i in range(13)]+[self.identity['namespace']],
            'backup_path':str(self.root/'backup.json')}

    def test_partial_patch_preserves_other_data_and_backup_has_no_credentials(self):
        plan=P.execute(self.args)
        changed=apply_patch(self.secret,plan['patch'])
        self.assertEqual(changed['data']['config'],self.secret['data']['config'])
        self.assertEqual(changed['data']['server'],self.secret['data']['server'])
        self.assertEqual({op['path'] for op in plan['patch'] if op['op']!='test'},
                         {'/data/namespaces','/data/clusterResources'})
        backup=Path(self.args['backup_path']);doc=json.loads(backup.read_text())
        self.assertEqual(set(doc['scope']),{'namespaces','clusterResources'})
        self.assertEqual(backup.stat().st_mode & 0o777,0o600)
        self.assertNotIn('config',doc);self.assertNotIn('server',doc)
        self.assertNotIn(self.secret['data']['config'],backup.read_text())
        with self.assertRaises(FileExistsError):P.execute(self.args)

    def test_cas_stale_uid_and_resource_version_abort(self):
        plan=P.execute(self.args)
        for field in ('uid','resourceVersion'):
            changed=copy.deepcopy(self.secret);changed['metadata'][field]='foreign'
            with self.assertRaises(ValueError):apply_patch(changed,plan['patch'])

    def test_foreign_owner_duplicate_server_and_wrong_local_server_rejected(self):
        for mutate in ('owner','uid','duplicate','server'):
            args=copy.deepcopy(self.args)
            if mutate=='owner':args['secrets'][0]['metadata']['ownerReferences'][0]['uid']='foreign'
            elif mutate=='uid':args['expected_secret_uid']='foreign'
            elif mutate=='duplicate':args['secrets'].append(copy.deepcopy(self.secret))
            else:args['secrets'][0]['data']['server']=encoded('https://foreign.invalid')
            with self.assertRaises(ValueError):P.execute(args)
            self.assertFalse(Path(args['backup_path']).exists())

    def test_wrong_or_duplicate_namespace_targets_fail_before_backup(self):
        for namespaces in ([self.identity['namespace']],self.args['namespaces']+['unapproved'],
                           self.args['namespaces']+[self.args['namespaces'][0]]):
            args=copy.deepcopy(self.args);args['namespaces']=namespaces
            with self.assertRaises(ValueError):P.execute(args)
            self.assertFalse(Path(args['backup_path']).exists())

    def test_active_application_operations_fail_before_any_write(self):
        for app in ({'operation':{}},{'operation':{'sync':{}}},
                    {'status':{'operationState':{'phase':'Running'}}},
                    {'status':{'operationState':{'phase':'Terminating'}}}):
            args=copy.deepcopy(self.args);args['applications']=[app]
            with self.assertRaises(ValueError):P.execute(args)
            self.assertFalse(Path(args['backup_path']).exists())

    def test_verified_namespace_order_is_semantic_and_other_fields_immutable(self):
        plan=P.execute(self.args);secret=apply_patch(self.secret,plan['patch'])
        secret['data']['namespaces']=encoded(','.join(reversed(self.args['namespaces'])))
        args=dict(self.args,operation='verificar',secrets=[secret],
                  expected_other_data_hash=plan['other_data_hash'])
        self.assertEqual(P.execute(args)['patch'],[])
        secret['data']['config']=encoded('rotated-fixture-credential')
        with self.assertRaises(ValueError):P.execute(args)

    def test_private_backup_rejects_git_paths_and_symlinks(self):
        for path in (ROOT/'scope-private.json',self.root/'link'):
            if path.name=='link':path.symlink_to(self.root/'target')
            args=dict(self.args,backup_path=str(path))
            with self.assertRaises(ValueError):P.execute(args)

    def test_native_role_only_patches_explicit_configure_and_waits_reconciliation(self):
        tasks=yaml.safe_load((ROLE/'tasks/scope.yml').read_text())
        writes=[t for t in tasks if 'kubernetes.core.k8s_json_patch' in t]
        self.assertEqual(len(writes),1)
        self.assertIn("platform_argocd_operation == 'configurar'",writes[0]['when'])
        self.assertTrue(writes[0]['no_log'])
        self.assertFalse(any('kubernetes.core.k8s' in t for t in tasks))
        pause=next(t for t in tasks if 'ansible.builtin.pause' in t)
        self.assertEqual(pause['ansible.builtin.pause']['seconds'],60)
        final=tasks[-1]
        self.assertEqual(final['platform_argocd_scope']['operation'],'verificar')
        self.assertEqual(final['platform_argocd_scope']['expected_other_data_hash'],
                         '{{ platform_argocd_scope_plan.other_data_hash }}')

    def test_actual_ansible_module_preserves_patch_and_never_emits_secret_data(self):
        proc=subprocess.run(ansible_python()+[str(ROLE/'library/platform_argocd_scope.py')],
            input=json.dumps({'ANSIBLE_MODULE_ARGS':self.args}),text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        result=json.loads(proc.stdout)
        self.assertEqual(result['patch'][0]['value'],'secret-uid')
        self.assertEqual(result['patch'][1]['value'],'17')
        self.assertTrue(result['_ansible_no_log'])
        self.assertNotIn(self.secret['data']['config'],proc.stdout)
        self.assertNotIn('fixture-private-credential',proc.stdout)

    def test_controller_transition_only_changes_one_owned_cr_field(self):
        instance={'apiVersion':'argoproj.io/v1beta1','kind':'ArgoCD',
                  'metadata':{'name':self.identity['name'],'namespace':self.identity['namespace'],
                              'uid':'instance-uid','resourceVersion':'21',
                              'labels':{'workshop.module':'connectivity-link','workshop.component':'platform-argocd'}},
                  'spec':{'controller':{'respectRBAC':'strict','other':'unchanged'}}}
        args=dict(self.args,operation='plan_controller',instance=instance,
                  owned_labels=instance['metadata']['labels'])
        plan=P.execute(args)
        writes=[p for p in plan['patch'] if p['op']=='replace']
        self.assertEqual(writes,[{'op':'replace','path':'/spec/controller/respectRBAC','value':'normal'}])
        self.assertEqual(plan['patch'][:2],[{'op':'test','path':'/metadata/uid','value':'instance-uid'},
                                         {'op':'test','path':'/metadata/resourceVersion','value':'21'}])
        self.assertEqual(json.loads(Path(args['backup_path']).read_text())['respectRBAC'],'strict')
        bad=copy.deepcopy(args);bad['instance']['metadata']['uid']='foreign'
        with self.assertRaises(ValueError):P.execute(bad)
        bad=copy.deepcopy(args);bad['applications']=[{'operation':{'sync':{}}}]
        with self.assertRaises(ValueError):P.execute(bad)
        bad=copy.deepcopy(args);bad['instance']['metadata']['labels']={}
        with self.assertRaises(ValueError):P.execute(bad)


if __name__ == '__main__':unittest.main()
