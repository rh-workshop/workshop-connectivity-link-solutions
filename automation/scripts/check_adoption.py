"""Gate SSA de adopción: únicamente lecturas y dry-run server, nunca apply real."""
import argparse
import base64
import binascii
import copy
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import yaml

sys.path.insert(0,str(Path(__file__).resolve().parent))
from git_source_proof import verify as verify_git_source
from platform_identity import load_identity
IDENTITY = load_identity()
RBAC_KINDS = {'Role','RoleBinding','ClusterRole','ClusterRoleBinding'}

SA = 'system:serviceaccount:'+IDENTITY['namespace']+':'+IDENTITY['service_account']
GROUPS = ['system:serviceaccounts', 'system:serviceaccounts:'+IDENTITY['namespace'], 'system:authenticated']
VOLATILE = {'uid', 'resourceVersion', 'generation', 'creationTimestamp', 'managedFields', 'selfLink'}
# Solo ownership de Argo/protección explícita. Todas las otras annotations/labels se comparan.
ADOPTION_ANNOTATIONS = {'argocd.argoproj.io/tracking-id', 'argocd.argoproj.io/installation-id',
                        'kubectl.kubernetes.io/last-applied-configuration'}
ADOPTION_LABELS = set()  # En annotation mode ninguna label queda excluida.


def key(resource):
    meta = resource['metadata']
    return '|'.join([resource['apiVersion'], resource['kind'], meta.get('namespace', ''), meta['name']])


def reference(resource):
    return {k: resource[k] for k in ('apiVersion', 'kind')} | {'metadata': {
        k: resource['metadata'][k] for k in ('name', 'namespace') if k in resource['metadata']}}


def normalize(resource):
    result = copy.deepcopy(resource)
    result.pop('status', None)
    metadata = result.get('metadata', {})
    if metadata.get('annotations', {}).get('argocd.argoproj.io/sync-options') == 'Prune=false,Delete=false':
        metadata['annotations'].pop('argocd.argoproj.io/sync-options')
    for field in VOLATILE:
        metadata.pop(field, None)
    for name, excluded in [('annotations', ADOPTION_ANNOTATIONS), ('labels', ADOPTION_LABELS)]:
        if name in metadata:
            metadata[name] = {k: v for k, v in metadata[name].items() if k not in excluded}
            if not metadata[name]: metadata.pop(name)
    return result


def differences(left, right, path='$'):
    """Solo rutas de campos; no expone valores, cuerpos ni credenciales en el informe."""
    if type(left) is not type(right): return [path]
    if isinstance(left, dict):
        result = []
        for field in sorted(set(left) | set(right)):
            child = f'{path}.{field}'
            result.extend([child] if field not in left or field not in right else differences(left[field], right[field], child))
        return result
    if isinstance(left, list):
        result = [path] if len(left) != len(right) else []
        for i, (a, b) in enumerate(zip(left, right)): result += differences(a, b, f'{path}[{i}]')
        return result
    return [] if left == right else [path]


def desired(folder):
    resources = []
    for path in sorted((folder / 'components').glob('*/manifests.yaml')):
        for resource in yaml.safe_load_all(path.read_text()):
            if not isinstance(resource, dict): raise ValueError('invalid_manifest')
            if resource.get('kind') in {'Secret', 'List', 'Namespace'} | RBAC_KINDS: raise ValueError('secret_or_list_in_desired')
            if resource.get('metadata', {}).get('annotations', {}).get('argocd.argoproj.io/sync-options') != 'Prune=false,Delete=false':
                raise ValueError('unsafe_resource_sync_options')
            key(resource)
            resources.append(resource)
    identities = [key(r) for r in resources]
    if not resources or len(set(identities)) != len(identities): raise ValueError('empty_or_duplicate_desired')
    if json.loads((folder/'handoff-blockers.json').read_text()): raise ValueError('unresolved_handoff_blockers')
    expected_map = json.loads((folder/'adoption-map.json').read_text())
    inventory = {'|'.join([r['apiVersion'], r['kind'], r.get('namespace', ''), r['name']]) for r in expected_map}
    if inventory != set(identities): raise ValueError('inventory_mismatch')
    applications = list((folder/'applications').glob('*.yaml'))
    if not applications: raise ValueError('missing_pinned_applications')
    application_names = set()
    for path in applications:
        app = yaml.safe_load(path.read_text())
        if app.get('apiVersion') != 'argoproj.io/v1alpha1' or app.get('kind') != 'Application' or app.get('metadata', {}).get('namespace') != IDENTITY['namespace']:
            raise ValueError('invalid_application_identity')
        application_names.add(app['metadata']['name'])
        revision = app['spec']['source']['targetRevision']
        if len(revision) != 40 or any(c not in '0123456789abcdef' for c in revision) or revision == '0'*40:
            raise ValueError('invalid_application_revision')
        options = app['spec']['syncPolicy']['syncOptions']
        if set(options) != {'ServerSideApply=true', 'ClientSideApplyMigration=false', 'FailOnSharedResource=true'} or 'automated' in app['spec']['syncPolicy'] or app['metadata'].get('finalizers'):
            raise ValueError('unsafe_application_sync_options')
    if application_names != {'cl-platform-'+r['phase'] for r in expected_map} or len(application_names) != len(applications):
        raise ValueError('application_phase_inventory_mismatch')
    return resources


def digest(resources):
    return hashlib.sha256(json.dumps(resources, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def applications_digest(folder):
    return digest({path.name:yaml.safe_load(path.read_text()) for path in sorted((folder/'applications').glob('*.yaml'))})


def one_resource(response, expected):
    """oc -f puede envolver un único objeto en List; nunca elegir entre varios."""
    if not isinstance(response, dict): raise ValueError('invalid_api_resource')
    if str(response.get('kind', '')).endswith('List'):
        items = response.get('items')
        if not isinstance(items, list): raise ValueError('invalid_api_list')
        if not items: raise ValueError('missing_resource')
        if len(items) != 1: raise ValueError('ambiguous_api_list')
        response = items[0]
    try:
        if key(response) != key(expected): raise ValueError('api_identity_mismatch')
    except (KeyError, TypeError): raise ValueError('invalid_api_resource') from None
    return response


class Oc:
    def run(self, args, resource=None, impersonate=True):
        command = ['oc']
        if impersonate:
            command += ['--as='+SA] + ['--as-group='+group for group in GROUPS]
        command += args
        result = subprocess.run(command, input=json.dumps(resource) if resource else None,
                                capture_output=True, text=True, timeout=120)
        if result.returncode:
            # stderr de API puede incluir cuerpo/valores: clasificar, nunca devolverlo.
            error = result.stderr.lower()
            code = 'access_denied' if 'forbidden' in error or 'unauthorized' in error else 'missing_resource' if 'notfound' in error or 'not found' in error else 'api_command_failed'
            raise ValueError(code)
        try: return json.loads(result.stdout)
        except json.JSONDecodeError: raise ValueError('invalid_api_json') from None

    def get(self, resource, impersonate=True):
        return one_resource(self.run(['get', '-f', '-', '-o', 'json'], reference(resource), impersonate), resource)

    def remote_reference(self, contract):
        pod = contract.get('repo_server', {})
        if not pod.get('name') or not pod.get('uid'):
            raise ValueError('git_remote_repo_server_guard_missing')
        reference = {'apiVersion':'v1','kind':'Pod','metadata':{'name':pod['name'],'namespace':IDENTITY['namespace']}}
        actual = self.get(reference, impersonate=False)
        if actual['metadata'].get('uid') != pod['uid']:
            raise ValueError('git_remote_repo_server_uid_mismatch')
        container = IDENTITY['repo_server_container']
        if container not in [c.get('name') for c in actual.get('spec',{}).get('containers',[])]:
            raise ValueError('git_remote_repo_server_container_missing')
        revision = contract['revision']
        ref = 'refs/tags/releases/'+revision
        result = subprocess.run(['oc','-n',IDENTITY['namespace'],'exec',pod['name'],'-c',container,'--',
                                 'git','ls-remote',contract['repo_url'],ref],capture_output=True,text=True,timeout=120)
        if result.returncode or result.stdout.strip().splitlines() != [revision+'\t'+ref]:
            raise ValueError('git_remote_release_reference_mismatch')
        if self.get(reference, impersonate=False)['metadata'].get('uid') != pod['uid']:
            raise ValueError('git_remote_repo_server_changed')
        return revision

    def role_bindings(self,namespace):
        response=self.run(['get','rolebindings','-n',namespace,'-o','json'],impersonate=False)
        if response.get('kind') not in {'List','RoleBindingList'} or not isinstance(response.get('items'),list):
            raise ValueError('invalid_namespace_rolebinding_list')
        if any(r.get('apiVersion') != 'rbac.authorization.k8s.io/v1' or r.get('kind') != 'RoleBinding' or r.get('metadata',{}).get('namespace') != namespace for r in response['items']):
            raise ValueError('namespace_rolebinding_identity_mismatch')
        return response['items']

    def can_i(self,verb,resource,namespace=None):
        command=['oc','--as='+SA]+['--as-group='+g for g in GROUPS]+['auth','can-i',verb]
        if resource=='serviceaccounts/token':command += ['serviceaccounts','--subresource=token']
        else:command.append(resource)
        if namespace: command += ['-n',namespace]
        result=subprocess.run(command,capture_output=True,text=True,timeout=120)
        if result.stdout.strip() not in {'yes','no'} or result.returncode not in {0,1}:
            raise ValueError('controller_permission_probe_failed')
        return result.stdout.strip()=='yes'

    def dry_run(self, resource):
        return one_resource(self.run(['apply', '--server-side', '--force-conflicts', '--dry-run=server',
                         '--field-manager=argocd-controller', '-f', '-', '-o', 'json'], resource), resource)


def external_contract(resource):
    kind, name = resource['kind'], resource['metadata']['name']
    if kind == 'ClusterIssuer':
        acme = resource.get('spec', {}).get('acme', {})
        if acme.get('server') != 'https://acme-v02.api.letsencrypt.org/directory' or not acme.get('solvers'):
            raise ValueError('external_issuer_wrong_configuration')
        if not any(c.get('type') == 'Ready' and str(c.get('status')).lower() == 'true' for c in resource.get('status', {}).get('conditions', [])):
            raise ValueError('external_issuer_not_ready')
    elif kind == 'CertManager':
        args = resource.get('spec', {}).get('controllerConfig', {}).get('overrideArgs', [])
        if '--dns01-recursive-nameservers-only' not in args or not any(a.startswith('--dns01-recursive-nameservers=') and len(a.split('=', 1)[1]) for a in args):
            raise ValueError('external_resolvers_missing')
        for flag in [a for a in args if a.startswith('--dns01-recursive-nameservers=')]:
            for endpoint in flag.split('=', 1)[1].split(','):
                try:
                    host, port = endpoint.rsplit(':', 1)
                    public = ipaddress.ip_address(host.strip('[]')).is_global and port == '53'
                except ValueError:
                    public = False
                if not public: raise ValueError('external_resolver_not_proven_public')
    elif kind == 'ConfigMap' and name == 'cluster-monitoring-config':
        config = yaml.safe_load(resource.get('data', {}).get('config.yaml', '{}'))
        if not isinstance(config, dict) or config.get('enableUserWorkload') is not True:
            raise ValueError('external_user_workload_monitoring_disabled')
    elif kind == 'Namespace':
        if resource.get('status',{}).get('phase') != 'Active' or resource['metadata'].get('deletionTimestamp'):
            raise ValueError('external_namespace_not_active')
    elif kind in RBAC_KINDS:
        if kind.endswith('Binding'):
            if not isinstance(resource.get('subjects'),list) or not isinstance(resource.get('roleRef'),dict):
                raise ValueError('external_rbac_schema_invalid')
        elif not isinstance(resource.get('rules'),list):
            raise ValueError('external_rbac_schema_invalid')
    else: raise ValueError('unknown_external_precondition')



def external_functional(resource):
    normalized=normalize(resource)
    fields=('spec','data','binaryData')
    if resource['kind'] == 'Namespace':
        fields += ('metadata',)
    if resource['kind'] in RBAC_KINDS:
        fields += ('metadata','rules','subjects','roleRef','aggregationRule')
    return {field:normalized[field] for field in fields if field in normalized}


def negative_checks():
    return [('patch','namespaces/kube-system',None), ('create','secrets','keycloak'),
            ('delete','namespaces/kuadrant-system',None),
            ('patch','configmaps/unlisted-adoption-negative-probe','rhcl-observability'),
            ('bind','clusterroles/cl-platform-argocd',None),
            ('escalate','clusterroles/cl-platform-argocd',None),
            ('create','serviceaccounts/token','keycloak'),
            ('create','subjectaccessreviews.authorization.k8s.io',None)]


def controller_guard(expected,client,namespaces=()):
    guard=expected.get('controller',{})
    if guard.get('identity') != IDENTITY or not guard.get('uid'):
        raise ValueError('missing_dedicated_controller_guard')
    reference={'apiVersion':'v1','kind':'ServiceAccount','metadata':{'name':IDENTITY['service_account'],'namespace':IDENTITY['namespace']}}
    live=client.get(reference,impersonate=False)
    if key(live)!=key(reference) or live['metadata'].get('uid')!=guard['uid']:
        raise ValueError('dedicated_controller_uid_mismatch')
    records=[]
    checks=negative_checks()+[(verb,'namespaces/'+name,None) for name in sorted(namespaces) for verb in ('patch','update')]
    for verb,resource,namespace in checks:
        allowed=client.can_i(verb,resource,namespace)
        records.append({'verb':verb,'resource':resource,'namespace':namespace,'allowed':allowed})
    if any(r['allowed'] for r in records):
        raise ValueError('dedicated_controller_effective_rbac_not_restricted')
    return records



def namespace_controller_isolation(namespace,client):
    labels=namespace['metadata'].get('labels',{})
    for name in ('argocd.argoproj.io/managed-by','argocd.argoproj.io/managed-by-cluster-argocd'):
        if labels.get(name) in {IDENTITY['namespace'],IDENTITY['name']}:
            raise ValueError('external_namespace_managed_by_platform_controller')
    for binding in client.role_bindings(namespace['metadata']['name']):
        if binding.get('roleRef',{}).get('name') not in {'admin','cluster-admin'}:continue
        for subject in binding.get('subjects',[]):
            matches=(subject.get('kind')=='ServiceAccount' and subject.get('name')==IDENTITY['service_account'] and subject.get('namespace')==IDENTITY['namespace']) or (subject.get('kind')=='User' and subject.get('name')==SA) or (subject.get('kind')=='Group' and subject.get('name') in GROUPS)
            if matches:raise ValueError('external_namespace_admin_binding_to_platform_controller')


def tracking_configuration(expected, client):
    guard = expected.get('tracking_config', {})
    if guard.get('apiVersion') != 'v1' or guard.get('kind') != 'ConfigMap' or guard.get('metadata', {}).get('namespace') != IDENTITY['namespace']:
        raise ValueError('missing_tracking_config_guard')
    live = client.get(guard, impersonate=False)
    if key(live) != key(guard) or not guard.get('uid') or live['metadata'].get('uid') != guard['uid']:
        raise ValueError('tracking_config_identity_mismatch')
    if 'data' not in guard or live.get('data', {}) != guard['data']:
        raise ValueError('tracking_config_drift')
    data = live.get('data', {})
    if data.get('resource.respectRBAC')!='normal':
        raise ValueError('controller_cache_rbac_mode_not_normal')
    if data.get('application.resourceTrackingMethod') != 'annotation':
        raise ValueError('tracking_method_not_proven_annotation_only')
    return live



def cluster_configuration_snapshot(secret, owner_cr_uid):
    """Contrato privado sin tokens/config plaintext: sólo scope y hashes."""
    reference={'apiVersion':'v1','kind':'Secret','metadata':{'name':IDENTITY['name']+'-default-cluster-config','namespace':IDENTITY['namespace']}}
    if key(secret)!=key(reference) or not secret['metadata'].get('uid') or secret.get('type')!='Opaque':
        raise ValueError('cluster_configuration_identity_invalid')
    metadata=secret['metadata']
    if metadata.get('deletionTimestamp') or metadata.get('labels',{}).get('argocd.argoproj.io/secret-type')!='cluster':
        raise ValueError('cluster_configuration_not_active_cluster_secret')
    owners=metadata.get('ownerReferences',[])
    if len(owners)!=1 or owners[0].get('kind')!='ArgoCD' or owners[0].get('apiVersion')!='argoproj.io/v1beta1' or owners[0].get('name')!=IDENTITY['name'] or owners[0].get('uid')!=owner_cr_uid or not owner_cr_uid:
        raise ValueError('cluster_configuration_owner_invalid')
    data=secret.get('data',{})
    try:
        public={name:base64.b64decode(data[name],validate=True).decode('utf-8') for name in ('name','server','namespaces','clusterResources')}
    except (KeyError,TypeError,ValueError,UnicodeError,binascii.Error):
        raise ValueError('cluster_configuration_data_invalid') from None
    if public['server']!='https://kubernetes.default.svc' or not re.fullmatch(r'[a-zA-Z0-9_.-]+',public['name']):
        raise ValueError('cluster_configuration_server_or_name_invalid')
    namespaces=public['namespaces'].split(',')
    if len(namespaces)!=len(set(namespaces)) or any(not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?',n) for n in namespaces):
        raise ValueError('cluster_configuration_namespace_list_invalid')
    if public['clusterResources']!='true':raise ValueError('cluster_configuration_cluster_resources_disabled')
    other={name:value for name,value in data.items() if name not in public}
    return reference|{'uid':metadata['uid'],'owner_cr_uid':owner_cr_uid,'server':public['server'],'name':public['name'],
                      'namespaces':sorted(namespaces),'cluster_resources':True,'other_data_sha256':digest(other),
                      'metadata_sha256':digest(normalize(secret)['metadata'])}


def cluster_configuration_guard(expected,client,namespaces):
    guard=expected.get('cluster_configuration',{})
    reference={'apiVersion':'v1','kind':'Secret','metadata':{'name':IDENTITY['name']+'-default-cluster-config','namespace':IDENTITY['namespace']}}
    if not guard.get('uid') or not guard.get('owner_cr_uid') or any(guard.get(k)!=v for k,v in reference.items()):
        raise ValueError('missing_cluster_configuration_guard')
    argo=client.get({'apiVersion':'argoproj.io/v1beta1','kind':'ArgoCD','metadata':{'name':IDENTITY['name'],'namespace':IDENTITY['namespace']}},impersonate=False)
    if argo.get('spec',{}).get('controller',{}).get('respectRBAC')!='normal':
        raise ValueError('controller_cache_cr_mode_not_normal')
    if argo['metadata'].get('uid')!=guard['owner_cr_uid'] or argo['metadata'].get('deletionTimestamp'):
        raise ValueError('cluster_configuration_argocd_uid_mismatch')
    actual=cluster_configuration_snapshot(client.get(reference,impersonate=False),guard['owner_cr_uid'])
    if actual['namespaces']!=sorted(set(namespaces)|{IDENTITY['namespace']}):
        raise ValueError('cluster_configuration_namespace_scope_mismatch')
    if guard!=actual:raise ValueError('cluster_configuration_snapshot_drift')
    return actual


def audit(folder, expected, client):
    resources = desired(folder)
    if expected.get('bundle_sha256') != digest(resources): raise ValueError('bundle_digest_mismatch')
    if expected.get('applications_sha256') != applications_digest(folder): raise ValueError('applications_digest_mismatch')
    if not expected.get('cluster_uid'): raise ValueError('missing_cluster_uid_guard')
    cluster = client.get({'apiVersion':'v1', 'kind':'Namespace', 'metadata':{'name':'kube-system'}}, impersonate=False)
    if cluster['metadata'].get('uid') != expected['cluster_uid']: raise ValueError('cluster_uid_mismatch')
    source_proof = verify_git_source(folder, expected.get('git_source', {}))
    if client.remote_reference(expected['git_source']) != source_proof['revision']:
        raise ValueError('git_remote_commit_mismatch')
    descriptors = json.loads((folder/'external-preconditions.json').read_text())
    external_namespaces={d['name'] for d in descriptors if d['kind']=='Namespace'}
    negative_baseline = controller_guard(expected,client,external_namespaces)
    configuration = cluster_configuration_guard(expected,client,external_namespaces)
    tracking = tracking_configuration(expected, client)
    installation = tracking.get('data', {}).get('installationID', '')
    guards = expected.get('resources', {})
    if set(guards) != {key(r) for r in resources} or any(not uid for uid in guards.values()): raise ValueError('missing_or_stale_resource_uid_guards')
    externals = [{'apiVersion':d['apiVersion'], 'kind':d['kind'], 'metadata':{k:d[k] for k in ('name','namespace') if k in d}} for d in descriptors]
    external_guards = expected.get('external', {})
    if set(external_guards) != {key(r) for r in externals}: raise ValueError('missing_or_stale_external_guards')
    if set(guards) & set(external_guards): raise ValueError('external_desired_ownership_collision')
    records = []
    phases = {'|'.join([r['apiVersion'],r['kind'],r.get('namespace',''),r['name']]):r['phase']
              for r in json.loads((folder/'adoption-map.json').read_text())}
    for resource in externals:
        identity = key(resource)
        record = {'identity':identity, 'external':True, 'errors':[]}
        try:
            live = client.get(resource, impersonate=False)
            if key(live) != identity: raise ValueError('external_identity_mismatch')
            guard = external_guards[identity]
            if not guard.get('uid') or live['metadata'].get('uid') != guard['uid']: raise ValueError('external_uid_mismatch')
            if live['metadata'].get('deletionTimestamp'): raise ValueError('external_resource_deleting')
            functional = external_functional(live)
            if not guard.get('functional') or differences(guard['functional'], functional): raise ValueError('external_configuration_drift')
            external_contract(live)
            if live['kind']=='Namespace':
                namespace_controller_isolation(live,client)
            descriptor = next(d for d in descriptors if '|'.join([d['apiVersion'],d['kind'],d.get('namespace',''),d['name']]) == identity)
            if live['kind'] in RBAC_KINDS:
                canonical=descriptor.get('canonical')
                if not canonical or differences(external_functional(canonical),functional):
                    raise ValueError('external_rbac_canonical_drift')
            if normalize(live) != normalize(client.get(resource, impersonate=False)): raise ValueError('external_changed_during_gate')
        except (ValueError, KeyError, TypeError, yaml.YAMLError) as error:
            record['errors'] = [str(error) if isinstance(error, ValueError) else 'invalid_external_schema']
        records.append(record)
    # No se hace ningún dry-run antes de verificar todos los prerrequisitos externos.
    if any(r['errors'] for r in records): return {'ok':False, 'records':records}
    for resource in resources:
        identity = key(resource)
        record = {'identity':identity, 'errors':[], 'changed_fields':[]}
        try:
            live = client.get(resource)
            if key(live) != identity: raise ValueError('resource_identity_mismatch')
            if live['metadata'].get('uid') != guards[identity]: raise ValueError('resource_uid_mismatch')
            if live['metadata'].get('deletionTimestamp'): raise ValueError('resource_deleting')
            meta = live['metadata']
            application = IDENTITY['name']+'-' + phases[identity]
            group = resource['apiVersion'].split('/')[0] if '/' in resource['apiVersion'] else ''
            tracking_id = f"{application}:{group}/{resource['kind']}:{meta.get('namespace','')}/{meta['name']}"
            previous = meta.get('annotations', {}).get('argocd.argoproj.io/tracking-id')
            previous_installation = meta.get('annotations', {}).get('argocd.argoproj.io/installation-id')
            if previous and previous != tracking_id or previous_installation and previous_installation != installation:
                raise ValueError('foreign_argocd_ownership')
            payload = copy.deepcopy(resource)
            annotations = payload['metadata'].setdefault('annotations', {})
            annotations['argocd.argoproj.io/tracking-id'] = tracking_id
            if installation: annotations['argocd.argoproj.io/installation-id'] = installation
            simulated = client.dry_run(payload)
            if key(simulated) != identity or simulated['metadata'].get('uid') != guards[identity]: raise ValueError('dry_run_identity_mismatch')
            record['changed_fields'] = differences(normalize(live), normalize(simulated))
            if record['changed_fields']: record['errors'].append('functional_drift')
            after = client.get(resource)
            if after['metadata'].get('uid') != guards[identity] or normalize(live) != normalize(after): raise ValueError('resource_changed_during_gate')
        except (ValueError, KeyError, TypeError) as error:
            record['errors'].append(str(error) if isinstance(error, ValueError) else 'invalid_resource_schema')
        records.append(record)
    if cluster_configuration_guard(expected,client,external_namespaces)!=configuration:
        records.append({'identity':key(configuration),'errors':['cluster_configuration_changed_during_gate']})
    if normalize(tracking) != normalize(client.get(tracking, impersonate=False)):
        records.append({'identity':key(tracking), 'errors':['tracking_config_changed_during_gate']})
    return {'ok':not any(r['errors'] for r in records), 'records':records,
            'bundle_sha256':digest(resources), 'applications_sha256':applications_digest(folder),
            'cluster_uid':expected['cluster_uid'], 'git_source_proof':source_proof,
            'impersonation':{'user':SA, 'groups':GROUPS}, 'controller':expected['controller'],
            'negative_permission_baseline':negative_baseline, 'cluster_configuration':configuration,
            'metadata_exceptions':sorted(ADOPTION_ANNOTATIONS | ADOPTION_LABELS),
            'tracking_method':'annotation', 'respect_rbac':'normal',
            'instance_label_key':tracking.get('data', {}).get('application.instanceLabelKey'),
            'protection_exception':'Only exact Prune=false,Delete=false; any other sync-option is compared/rejected.'}


def private_report(path, report):
    path = path.expanduser().resolve()
    if any((parent/'.git').exists() for parent in [path.parent, *path.parents]): raise ValueError('report_must_be_outside_git')
    # Rechazar symlinks/no sobrescribir informes previos. El directorio debe existir.
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream: json.dump(report, stream, indent=2); stream.write('\n')


def private_expectations(path):
    path = path.expanduser().resolve()
    if any((parent/'.git').exists() for parent in path.parents): raise ValueError('expectations_must_be_outside_git')
    if path.stat().st_mode & 0o077: raise ValueError('expectations_must_be_private')
    return json.loads(path.read_text())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render-dir', type=Path, required=True)
    parser.add_argument('--expected', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = audit(args.render_dir, private_expectations(args.expected), Oc())
    except (ValueError, KeyError, OSError, subprocess.TimeoutExpired, yaml.YAMLError) as error:
        code = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[a-z_]+', str(error)) else 'adoption_gate_failed_before_completion'
        report = {'ok':False, 'errors':[code]}
    try: private_report(args.report, report)
    except (ValueError, OSError):
        print('FAIL: informe requiere ruta nueva privada fuera de Git', file=sys.stderr); return 1
    print('PASS: dry-run SSA sin deriva' if report['ok'] else 'FAIL: revisar informe privado; no se aplicaron cambios')
    return 0 if report['ok'] else 1


if __name__ == '__main__': sys.exit(main())
