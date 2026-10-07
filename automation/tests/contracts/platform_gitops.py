"""Pruebas offline de publicación, identidad y readiness de plataforma."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import yaml

ROOT = Path(__file__).resolve().parents[3]


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


R = module('render_platform', ROOT/'automation/scripts/render_platform.py')


class Platform(unittest.TestCase):
    def test_all_rbac_is_external_and_controller_cannot_write_rbac(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'values.yml';values=yaml.safe_load((R.ROOT/'platform/kustomize/overlays/example/values.yml').read_text())
            values['lab05_ksm_image']='registry.example.com/ksm@sha256:'+'a'*64;path.write_text(yaml.safe_dump(values))
            out=Path(tmp)/'out';identities=R.render(path,out,'https://github.com/example/platform.git','a'*40,'platform')
            self.assertFalse(any(r['kind'] in R.RBAC_KINDS | {'Namespace'} for r in identities))
            self.assertFalse((out/'components/rbac').exists())
            external=json.loads((out/'external-preconditions.json').read_text())
            self.assertTrue(any(r['kind']=='ClusterRoleBinding' and r['name']=='kube-state-metrics-kuadrant' for r in external))
            access=list(yaml.safe_load_all((out/'access/project-and-rbac.yaml').read_text()))
            self.assertEqual(access[0]['metadata']['namespace'],R.IDENTITY['namespace'])
            for obj in access:
                for subject in obj.get('subjects',[]):
                    self.assertEqual(subject['namespace'],R.IDENTITY['namespace']);self.assertEqual(subject['name'],R.IDENTITY['service_account'])
                for rule in obj.get('rules',[]):
                    self.assertNotIn('rbac.authorization.k8s.io',rule['apiGroups'])
                    if 'namespaces' in rule['resources']:self.assertTrue(set(rule['verbs']) <= {'get','list','watch'})
            self.assertNotIn({'group':'','kind':'Namespace'},access[0]['spec']['clusterResourceWhitelist'])
            self.assertTrue((out/'bootstrap/external-namespaces.yaml').exists())
            with self.assertRaisesRegex(ValueError,'bootstrap externo'):
                R.access_documents([{'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRole','metadata':{'name':'forbidden'}}],'https://github.com/example/platform.git')

    def test_only_openshift_tempo_requires_ephemeral_tokenreview_create(self):
        resource={'apiVersion':'tempo.grafana.com/v1alpha1','kind':'TempoMonolithic','metadata':{'name':'tracing','namespace':'tempo'},'spec':{'multitenancy':{'mode':'openshift'}}}
        def creates(resources):
            return [rule for obj in R.access_documents(resources,'https://github.com/example/platform.git') for rule in obj.get('rules',[]) if 'create' in rule['verbs']]
        self.assertEqual(creates([resource]),[{'apiGroups':['authentication.k8s.io'],'resources':['tokenreviews'],'verbs':['create']}])
        for mode in ['static','',None]:
            resource['spec']['multitenancy']['mode']=mode
            self.assertEqual(creates([resource]),[])
        self.assertEqual(creates([{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'tracing','namespace':'tempo'}}]),[])
        resource['spec']['multitenancy']['mode']='openshift';resource['apiVersion']='other.example.com/v1'
        self.assertEqual(creates([resource]),[])

    def test_normal_cache_union_reads_all_scoped_namespaces_without_write_expansion(self):
        resources=[{'apiVersion':'v1','kind':'ConfigMap','metadata':{'name':'one','namespace':'istio-system'}},
                   {'apiVersion':'apps/v1','kind':'Deployment','metadata':{'name':'two','namespace':'keycloak'}}]
        scope={'istio-system','keycloak','tempo'}
        access=R.access_documents(resources,'https://github.com/example/platform.git',scope)
        roles=[r for r in access if r['kind']=='Role']
        self.assertEqual({r['metadata']['namespace'] for r in roles},scope|{R.IDENTITY['namespace']})
        for role in roles:
            read=[r for r in role['rules'] if set(r['verbs'])=={'list','watch'}]
            self.assertEqual({(r['apiGroups'][0],r['resources'][0]) for r in read},{('','configmaps'),('apps','deployments')})
            self.assertTrue(all('resourceNames' not in r for r in read))
            writes=[r for r in role['rules'] if 'patch' in r['verbs']]
            if role['metadata']['namespace'] in {'tempo',R.IDENTITY['namespace']}:self.assertEqual(writes,[])
            for rule in writes:self.assertEqual(rule['resourceNames'],['one'] if role['metadata']['namespace']=='istio-system' else ['two'])
            self.assertFalse(any('secrets' in r['resources'] or 'horizontalpodautoscalers' in r['resources'] or '*' in str(r) for r in role['rules']))
        cluster=next(r for r in access if r['kind']=='ClusterRole')
        namespace_get=next(r for r in cluster['rules'] if r['resources']==['namespaces'] and r['verbs']==['get'])
        self.assertEqual(set(namespace_get['resourceNames']),scope|{R.IDENTITY['namespace']})

    def test_parent_tracing_and_explicit_plugin_exception(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'out'
            values=yaml.safe_load((R.ROOT/'platform/kustomize/overlays/example/values.yml').read_text())
            values['lab05_ksm_image']='registry.example.com/ksm@sha256:'+'a'*64
            path=Path(tmp)/'values.yml';path.write_text(yaml.safe_dump(values))
            identities=R.render(path,output,'https://github.com/example/platform.git','a'*40,'platform')
            self.assertFalse(any(r['kind']=='Authorino' or r['name']=='kuadrant-console-plugin' for r in identities))
            kuadrant=yaml.safe_load((output/'components/kuadrant/manifests.yaml').read_text())
            self.assertTrue(kuadrant['spec']['observability']['tracing']['defaultEndpoint'].startswith('rpc://'))
            self.assertEqual(json.loads((output/'handoff-blockers.json').read_text()),[])
            patches=json.loads((output/'observability-patches.json').read_text())
            self.assertEqual({p['kind'] for p in patches},{'Istio','Kuadrant'})
            actions=json.loads((output/'runtime-actions.json').read_text())
            self.assertEqual(actions[0]['role'],'console_plugin_configuration')
            self.assertIn('console_plugin_verificar_solo=false',actions[0]['apply'])
            self.assertEqual({a['action'] for a in actions},{'metrics-workload-suffix','console-plugin-enablement'})
            enable=next(a for a in actions if a['action']=='console-plugin-enablement')
            self.assertEqual(enable['resource'],{'apiVersion':'operator.openshift.io/v1','kind':'Console','name':'cluster'})
            self.assertEqual(enable['verification_tasks'],'common/roles/console_plugin_configuration/tasks/habilitacion.yml')
            self.assertIn('CAS',enable['write_scope'])
            self.assertFalse(any(r['kind'] in {'Console','ConsolePlugin'} for r in identities))
            access=list(yaml.safe_load_all((output/'access/project-and-rbac.yaml').read_text()))
            self.assertFalse(any('consoles' in rule['resources'] or 'consoleplugins' in rule['resources'] for r in access for rule in r.get('rules',[])))
            self.assertNotIn('=false',actions[0]['verify'])
            parity=json.loads((output/'source-parity.json').read_text())
            self.assertIn('common/roles/console_plugin_configuration/tasks/patch.yml',parity)

    def test_gateway_defaults_opt_in_annotations_and_access(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = yaml.safe_load((R.ROOT/'platform/kustomize/overlays/example/values.yml').read_text())
            values['aws_load_balancer_subnet_ids']=['subnet-0123456789abcdef0','subnet-fedcba98765432100']
            path=Path(tmp)/'values.yml';path.write_text(yaml.safe_dump(values))
            output=Path(tmp)/'out'
            R.render(path,output,'https://github.com/example/platform.git','a'*40,'platform')
            overlay=yaml.safe_load((output/'overlays/example/kustomization.yaml').read_text())
            phases=[Path(p).name for p in overlay['resources']]
            self.assertEqual(phases[phases.index('istio')+1],'gateway-defaults')
            cm=yaml.safe_load((output/'components/gateway-defaults/manifests.yaml').read_text())
            self.assertEqual(cm['metadata']['namespace'],'istio-system')
            self.assertEqual(cm['metadata']['labels']['gateway.istio.io/defaults-for-class'],'istio')
            patch=yaml.safe_load(cm['data']['service'])
            self.assertEqual(patch,{'metadata':{'annotations':{
                'service.beta.kubernetes.io/aws-load-balancer-subnets':','.join(values['aws_load_balancer_subnet_ids'])}}})
            parity=json.loads((output/'source-parity.json').read_text())
            for name in ['defaults/main.yml','templates/configmap.yaml.j2']:
                source='common/roles/gateway_defaults/'+name
                self.assertEqual(parity[source],hashlib.sha256((R.ROOT/source).read_bytes()).hexdigest())
            access=list(yaml.safe_load_all((output/'access/project-and-rbac.yaml').read_text()))
            self.assertIn({'group':'','kind':'ConfigMap'},access[0]['spec']['namespaceResourceWhitelist'])
            role=next(r for r in access if r['kind']=='Role' and r['metadata']['namespace']=='istio-system')
            self.assertTrue(any('configmaps' in r['resources'] for r in role['rules']))

    def test_gateway_defaults_reject_invalid_or_duplicate_subnets(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'values.yml'
            for ids in ['subnet-01234567',['bad'],['subnet-01234567','subnet-01234567']]:
                path.write_text(yaml.safe_dump({'aws_load_balancer_subnet_ids':ids}))
                with self.assertRaises(ValueError):R.render(path,Path(tmp)/'out')

    def test_lab11_specialization_survives_shared_defaults(self):
        fixture=yaml.safe_load((R.ROOT/'tests/fixtures/render-all.yml').read_text())
        values={**fixture['shared'],**fixture['roles']['lab11'],
                'aws_load_balancer_subnet_ids':['subnet-01234567'],
                'aws_gateway_subnets_override':False}
        template=R.ROOT/'labs/lab11/roles/lab11/templates/gateway.yaml.j2'
        gateway=R.project(template,values)[0]
        annotations=gateway['spec']['infrastructure']['annotations']
        self.assertEqual(annotations['service.beta.kubernetes.io/aws-load-balancer-proxy-protocol'],'*')
        self.assertNotIn('service.beta.kubernetes.io/aws-load-balancer-subnets',annotations)
        self.assertEqual(gateway['spec']['infrastructure']['parametersRef']['name'],values['lab11_gateway']+'-infra')
        values['aws_gateway_subnets_override']=True
        gateway=R.project(template,values)[0]
        self.assertEqual(gateway['spec']['infrastructure']['annotations']['service.beta.kubernetes.io/aws-load-balancer-subnets'],'subnet-01234567')

    def test_keycloak_replaces_forwarded_headers_via_operator_owned_ingress(self):
        with tempfile.TemporaryDirectory() as tmp:
            values=yaml.safe_load((R.ROOT/'platform/kustomize/overlays/example/values.yml').read_text())
            path=Path(tmp)/'values.yml';path.write_text(yaml.safe_dump(values))
            output=Path(tmp)/'out';R.render(path,output)
            resources=list(yaml.safe_load_all((output/'components/keycloak/manifests.yaml').read_text()))
            instances=[resource for resource in resources if resource['kind']=='Keycloak']
            self.assertEqual(len(instances),1)
            instance=instances[0]
            self.assertEqual(instance['metadata']['name'],values['keycloak_cr_nombre'])
            self.assertEqual(instance['metadata']['namespace'],values['keycloak_namespace'])
            self.assertEqual(instance['spec']['ingress'],{'annotations':{
                'haproxy.router.openshift.io/set-forwarded-headers':'replace'}})
            # Full remaining CR contract: trust change must not alter DB, hostname,
            # instance count, bootstrap credentials references or TLS/proxy mode.
            remaining=dict(instance['spec']);remaining.pop('ingress')
            self.assertEqual(remaining,{
                'instances':1,
                'bootstrapAdmin':{'user':{'secret':values['keycloak_admin_secret']}},
                'db':{'vendor':'postgres','host':'postgres-db','port':5432,'database':'keycloak',
                      'usernameSecret':{'name':'keycloak-db-secret','key':'username'},
                      'passwordSecret':{'name':'keycloak-db-secret','key':'password'}},
                'hostname':{'hostname':'https://console-keycloak.'+values['wk_ocp_domain']},
                'http':{'httpEnabled':True},
                'proxy':{'headers':'xforwarded'},
            })
            self.assertFalse(any(resource['kind'] in {'Ingress','Route','IngressController'}
                                 for resource in resources))

    def test_adoption_preserves_vendor_labels_and_common_keycloak_ownership(self):
        source={'apiVersion':'v1','kind':'Service','metadata':{'name':'ksm','labels':{'app.kubernetes.io/part-of':'kuadrant'}}}
        self.assertEqual(R.sanitize(source)['metadata']['labels']['app.kubernetes.io/part-of'],'kuadrant')
        bare={'apiVersion':'v1','kind':'Namespace','metadata':{'name':'tempo'}}
        self.assertNotIn('labels',R.sanitize(bare)['metadata'])
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'out';R.render(R.ROOT/'platform/kustomize/overlays/example/values.yml',output)
            keycloak=list(yaml.safe_load_all((output/'components/keycloak/manifests.yaml').read_text()))
            instance=next(r for r in keycloak if r['kind']=='Keycloak')
            self.assertEqual(instance['metadata']['labels']['workshop.module'],'connectivity-link')

    def test_projection_and_no_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'out'
            identities = R.render(R.ROOT/'platform/kustomize/overlays/example/values.yml', output)
            self.assertFalse(any(r['kind']=='Secret' for r in identities))
            self.assertFalse(any(r['kind']=='Namespace' and r['name']=='openshift-operators' for r in identities))
            resources = list(yaml.safe_load_all((output/'components/istio/manifests.yaml').read_text()))
            self.assertEqual(resources[0]['metadata']['name'], 'default')
            self.assertTrue(resources[0]['spec']['values']['meshConfig']['enableTracing'])
            self.assertTrue((output/'source-parity.json').exists())
            for name, expected in json.loads((output/'source-parity.json').read_text()).items():
                self.assertEqual(hashlib.sha256((R.ROOT/name).read_bytes()).hexdigest(), expected)
            required = json.loads((output/'required-secrets.json').read_text())
            self.assertTrue(any(s['name']=='grafana-thanos-token' for s in required))
            self.assertNotIn('NO_PUBLICAR', '\n'.join(p.read_text() for p in output.rglob('*') if p.is_file()))
            for path in (output/'components').glob('*/manifests.yaml'):
                for resource in yaml.safe_load_all(path.read_text()):
                    options=resource['metadata']['annotations']['argocd.argoproj.io/sync-options']
                    self.assertEqual(options,'Prune=false,Delete=false')
                    self.assertNotIn('Force',options)
                    self.assertNotIn('Replace',options)

    def test_reject_credentials(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = Path(tmp)/'values.yml'
            values.write_text('keycloak_db_password: secret\n')
            with self.assertRaises(ValueError):
                R.render(values, Path(tmp)/'out')

    def test_apps_manual_without_finalizer(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp)/'out'
            R.render(R.ROOT/'platform/kustomize/overlays/example/values.yml', output,
                     'https://github.com/example/platform.git', 'a'*40, 'platform')
            self.assertEqual(len(list((output/'applications').glob('*.yaml'))), 7)
            for path in (output/'applications').glob('*.yaml'):
                app = yaml.safe_load(path.read_text())
                self.assertNotIn('automated', app['spec']['syncPolicy'])
                self.assertNotIn('finalizers', app['metadata'])
                self.assertEqual(app['spec']['project'],R.IDENTITY['name'])
                self.assertEqual(app['metadata']['namespace'],R.IDENTITY['namespace'])
                self.assertEqual(app['spec']['syncPolicy']['syncOptions'],['FailOnSharedResource=true','ServerSideApply=true','ClientSideApplyMigration=false'])
            access=list(yaml.safe_load_all((output/'access/project-and-rbac.yaml').read_text()))
            project=access[0]
            self.assertEqual(project['kind'],'AppProject')
            self.assertEqual(project['spec']['sourceRepos'],['https://github.com/example/platform.git'])
            self.assertFalse(any(d['namespace']=='cl-platform-gitops' for d in project['spec']['destinations']))
            self.assertFalse(any(r['kind'] in {'Secret','CustomResourceDefinition','ClusterServiceVersion'}
                                 for r in project['spec']['namespaceResourceWhitelist']+project['spec']['clusterResourceWhitelist']))
            for resource in access[1:]:
                for rule in resource.get('rules',[]):
                    self.assertNotIn('*',rule['resources'])
                    self.assertNotIn('*',rule['verbs'])
                    self.assertNotIn('delete',rule['verbs'])
                    if 'create' in rule['verbs']:
                        self.assertEqual(rule,{'apiGroups':['authentication.k8s.io'],'resources':['tokenreviews'],'verbs':['create']})
                    self.assertFalse({'deletecollection','escalate','bind'} & set(rule['verbs']))
                    if {'get','update','patch'} & set(rule['verbs']):
                        self.assertTrue(rule.get('resourceNames'), rule)
                    if 'list' in rule['verbs'] or 'watch' in rule['verbs']:
                        self.assertNotIn('resourceNames',rule)
                    if 'clusterserviceversions' in rule['resources']:
                        self.assertEqual(rule['verbs'],['list','watch'])

    def test_resource_names_are_scoped_to_namespace_and_revision_is_not_zero(self):
        resources = [dict(apiVersion='v1',kind='ConfigMap',metadata={'name':'config-a','namespace':'istio-system'}),
                     dict(apiVersion='v1',kind='ConfigMap',metadata={'name':'config-b','namespace':'keycloak'})]
        access = R.access_documents(resources,'https://github.com/example/platform.git')
        for role in [r for r in access if r['kind']=='Role']:
            namespace=role['metadata']['namespace']
            writes=[rule for rule in role['rules'] if 'patch' in rule['verbs']]
            if namespace==R.IDENTITY['namespace']:
                self.assertEqual(writes,[])
            else:
                expected = 'config-a' if namespace=='istio-system' else 'config-b'
                self.assertEqual(writes[0]['resourceNames'],[expected])
                self.assertEqual(writes[0]['verbs'],['get','update','patch'])
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError):
                R.render(R.ROOT/'platform/kustomize/overlays/example/values.yml',Path(tmp)/'out',
                         'https://github.com/example/platform.git','0'*40,'platform')

    def test_external_preconditions_are_not_desired_or_exported_as_secrets(self):
        with tempfile.TemporaryDirectory() as tmp:
            output=Path(tmp)/'out'
            identities=R.render(R.ROOT/'platform/kustomize/overlays/example/values.yml',output)
            external=json.loads((output/'external-preconditions.json').read_text())
            self.assertEqual({r['kind'] for r in external},{'ClusterIssuer','CertManager','ConfigMap','ClusterRole','ClusterRoleBinding','Namespace'})
            identities={(r['apiVersion'],r['kind'],r.get('namespace',''),r['name']) for r in identities}
            for r in external:
                self.assertNotIn((r['apiVersion'],r['kind'],r.get('namespace',''),r['name']),identities)
                self.assertNotIn('data',r)

    def test_opt_in_ingress_no_immediate_controller_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            values = yaml.safe_load((R.ROOT/'platform/kustomize/overlays/example/values.yml').read_text())
            values.update(ingress_certificate_enabled=True,ingress_domain='apps.cluster.example.com',
                          acme_dns_zone='example.com',acme_route53_hosted_zone_id='EXAMPLE',
                          acme_route53_region='us-east-1')
            path=Path(tmp)/'values.yml';path.write_text(yaml.safe_dump(values))
            output=Path(tmp)/'out';identities=R.render(path,output)
            resources=list(yaml.safe_load_all((output/'components/ingress-certificate/manifests.yaml').read_text()))
            issuer,certificate=resources
            self.assertEqual(issuer['kind'],'Issuer')
            self.assertEqual(issuer['metadata']['namespace'],'openshift-ingress')
            self.assertEqual(certificate['spec']['dnsNames'],['apps.cluster.example.com','*.apps.cluster.example.com'])
            self.assertFalse(any(r['kind']=='IngressController' for r in identities))
            self.assertFalse(any(r['kind']=='Secret' for r in identities))

    def test_internal_repo_is_exact_and_opt_in(self):
        with tempfile.TemporaryDirectory() as tmp:
            values=yaml.safe_load((R.ROOT/'platform/kustomize/overlays/example/values.yml').read_text())
            values.update(publication_mode='internal',wk_ocp_domain='apps.cluster.private.example.net')
            path=Path(tmp)/'values.yml';path.write_text(yaml.safe_dump(values))
            with self.assertRaises(ValueError):R.render(path,Path(tmp)/'bad','http://untrusted/repo','a'*40,'platform')
            R.render(path,Path(tmp)/'out',R.INTERNAL_REPO,'a'*40,'platform')

    def test_internal_component_render_breaks_sha_cycle_without_fake_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            values=yaml.safe_load((R.ROOT/'platform/kustomize/overlays/example/values.yml').read_text())
            values.update(publication_mode='internal',wk_ocp_domain='apps.cluster.private.example.net')
            path=Path(tmp)/'values.yml';path.write_text(yaml.safe_dump(values))
            output=Path(tmp)/'components-only';R.render(path,output)
            self.assertTrue((output/'components/istio/manifests.yaml').exists())
            self.assertFalse((output/'applications').exists())
            self.assertFalse((output/'access').exists())
            for index,args in enumerate([(R.INTERNAL_REPO,None,None),(None,'a'*40,'platform'),(None,None,'platform')]):
                with self.assertRaises(ValueError):R.render(path,Path(tmp)/f'partial{index}',*args)


if __name__=='__main__':
    unittest.main()
