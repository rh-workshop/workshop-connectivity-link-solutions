"""Proyectar fuentes canónicas a un árbol Kustomize sin secretos ni sincronización."""
import argparse
import copy
import hashlib
import ipaddress
import json
from pathlib import Path
import re
import sys

from jinja2 import Environment, StrictUndefined
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
from platform_identity import load_identity, SOURCE as IDENTITY_SOURCE
IDENTITY = load_identity()
RBAC_KINDS = {'Role', 'RoleBinding', 'ClusterRole', 'ClusterRoleBinding'}

ROOT = Path(__file__).resolve().parents[1]
ENV = Environment(undefined=StrictUndefined, keep_trailing_newline=True)
ENV.filters['to_json'] = json.dumps
LABEL = {'app.kubernetes.io/part-of': 'connectivity-link'}
PHASES = ['operators', 'istio-cni', 'istio', 'kuadrant', 'cert-manager', 'keycloak', 'observability']
INTERNAL_REPO = 'http://cl-platform-git-repository.cl-platform-gitops.svc:8080/platform.git'
PLATFORM_NAMESPACES = {'kuadrant-system','openshift-operators','cert-manager-operator','keycloak',
                       'tempo','grafana-rhcl','rhcl-observability','istio-system','istio-cni',
                       'openshift-tempo-operator','openshift-opentelemetry-operator',
                       'openshift-cluster-observability-operator','openshift-ingress'}


def load(path):
    return yaml.safe_load(path.read_text())


def project(path, values):
    return [r for r in yaml.safe_load_all(ENV.from_string(path.read_text()).render(**values)) if r]


def merge(target, patch):
    for key, value in patch.items():
        if isinstance(value, dict) and isinstance(target.get(key), dict):
            merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)


def sanitize(resource):
    if resource['kind'] == 'Secret':
        return None
    if resource['kind'] in {'CustomResourceDefinition', 'ClusterServiceVersion', 'InstallPlan'}:
        raise ValueError('El operador conserva sus recursos generados')
    text = yaml.safe_dump(resource)
    if re.search(r'(?i)(?:https?://)?(?:127\.0\.0\.1|localhost|10\.\d+\.\d+\.\d+|192\.168\.\d+\.\d+)(?:[:/\s]|$)', text):
        raise ValueError('No publicar endpoints privados')
    # Preservar labels funcionales/canónicas; tracking Argo no exige part-of global.
    resource.setdefault('metadata', {})
    resource['metadata'].setdefault('annotations', {})['argocd.argoproj.io/sync-options'] = 'Prune=false,Delete=false'
    return resource


def access_documents(resources, repo_url, external_namespaces=None):
    """Permisos iniciales explícitos; no otorga Secret/CRD/CSV writes ni self-admin."""
    if any(r['kind'] in RBAC_KINDS | {'Namespace'} for r in resources):
        raise ValueError('Platform RBAC/Namespace es bootstrap externo; nunca conceder escritura al controlador')
    namespaces = {r['metadata']['namespace'] for r in resources if r['metadata'].get('namespace')}
    namespace_objects = set(external_namespaces or namespaces)
    namespace_objects |= {r['spec']['namespace'] for r in resources if r['kind'] in {'Istio','IstioCNI'}}
    if not namespaces | namespace_objects <= PLATFORM_NAMESPACES:
        raise ValueError('Namespace fuera del ámbito fijo de plataforma')
    cluster_types = {(r['apiVersion'].split('/')[0] if '/' in r['apiVersion'] else '',r['kind'])
                     for r in resources if not r['metadata'].get('namespace')}
    namespaced_types = {(r['apiVersion'].split('/')[0] if '/' in r['apiVersion'] else '',r['kind'])
                        for r in resources if r['metadata'].get('namespace')}
    project = {'apiVersion':'argoproj.io/v1alpha1','kind':'AppProject',
               'metadata':{'name':IDENTITY['name'],'namespace':IDENTITY['namespace']},
               'spec':{'sourceRepos':[repo_url],
                       'destinations':[{'server':'https://kubernetes.default.svc','namespace':n} for n in sorted(namespaces | {''})],
                       'clusterResourceWhitelist':[{'group':g,'kind':k} for g,k in sorted(cluster_types)],
                       'namespaceResourceWhitelist':[{'group':g,'kind':k} for g,k in sorted(namespaced_types)]}}
    result = [sanitize(project)]
    plural = {'Namespace':'namespaces','ClusterRole':'clusterroles','ClusterRoleBinding':'clusterrolebindings',
              'OperatorGroup':'operatorgroups','Subscription':'subscriptions','Istio':'istios','IstioCNI':'istiocnis',
              'Kuadrant':'kuadrants','ClusterIssuer':'clusterissuers','Keycloak':'keycloaks','Deployment':'deployments',
              'Service':'services','ServiceAccount':'serviceaccounts','PersistentVolumeClaim':'persistentvolumeclaims',
              'ConfigMap':'configmaps','Role':'roles','RoleBinding':'rolebindings','Telemetry':'telemetries',
              'Grafana':'grafanas','GrafanaDatasource':'grafanadatasources','GrafanaFolder':'grafanafolders',
              'GrafanaDashboard':'grafanadashboards','TempoMonolithic':'tempomonolithics','UIPlugin':'uiplugins',
              'OpenTelemetryCollector':'opentelemetrycollectors','ServiceMonitor':'servicemonitors',
              'Issuer':'issuers','Certificate':'certificates'}
    subject = {'kind':'ServiceAccount','name':IDENTITY['service_account'],'namespace':IDENTITY['namespace']}
    cache_namespaces=namespace_objects|{IDENTITY['namespace']}
    rules = [{'apiGroups':[''],'resources':['namespaces'],'resourceNames':sorted(cache_namespaces),'verbs':['get']},
             {'apiGroups':[''],'resources':['namespaces'],'verbs':['list','watch']}]
    for group,kind in sorted(cluster_types):
        names = sorted({r['metadata']['name'] for r in resources if r['kind']==kind and not r['metadata'].get('namespace') and
                        (r['apiVersion'].split('/')[0] if '/' in r['apiVersion'] else '') == group})
        rules.append({'apiGroups':[group],'resources':[plural[kind]],'resourceNames':names,'verbs':['get','update','patch']})
        rules.append({'apiGroups':[group],'resources':[plural[kind]],'verbs':['list','watch']})
    # Excepción efímera mínima: el admission webhook Tempo OpenShift verifica tokens.
    if any(r['kind']=='TempoMonolithic' and r['apiVersion'].split('/')[0]=='tempo.grafana.com'
           and r.get('spec',{}).get('multitenancy',{}).get('mode')=='openshift' for r in resources):
        rules.append({'apiGroups':['authentication.k8s.io'],'resources':['tokenreviews'],'verbs':['create']})
    role = {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRole',
            'metadata':{'name':'cl-platform-argocd'},'rules':rules}
    binding = {'apiVersion':'rbac.authorization.k8s.io/v1','kind':'ClusterRoleBinding',
               'metadata':{'name':'cl-platform-argocd'},'subjects':[subject],
               'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'cl-platform-argocd'}}
    result += [sanitize(role),sanitize(binding)]
    for namespace in sorted(cache_namespaces):
        kinds = {(r['apiVersion'].split('/')[0] if '/' in r['apiVersion'] else '',r['kind'])
                 for r in resources if r['metadata'].get('namespace')==namespace}
        rules = []
        for group, kind in sorted(kinds):
            names = sorted({r['metadata']['name'] for r in resources
                            if r['metadata'].get('namespace') == namespace and r['kind'] == kind and
                            (r['apiVersion'].split('/')[0] if '/' in r['apiVersion'] else '') == group})
            rules.append({'apiGroups':[group],'resources':[plural[kind]],'resourceNames':names,'verbs':['get','update','patch']})
        # El cache normal descarta un tipo al primer Forbidden: unión finita en todo el scope.
        for group,kind in sorted(namespaced_types):
            rules.append({'apiGroups':[group],'resources':[plural[kind]],'verbs':['list','watch']})
        # Leer readiness de objetos generados OLM no implica adoptarlos.
        if any(k=='Subscription' for g,k in kinds):
            rules.append({'apiGroups':['operators.coreos.com'],'resources':['clusterserviceversions'],'verbs':['list','watch']})
        result.append(sanitize({'apiVersion':'rbac.authorization.k8s.io/v1','kind':'Role',
                                'metadata':{'name':'cl-platform-argocd','namespace':namespace},'rules':rules}))
        result.append(sanitize({'apiVersion':'rbac.authorization.k8s.io/v1','kind':'RoleBinding',
                                'metadata':{'name':'cl-platform-argocd','namespace':namespace},'subjects':[subject],
                                'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'Role','name':'cl-platform-argocd'}}))
    return result


def render(values_path, output, repo_url=None, revision=None, published_path=None):
    supplied = load(values_path)
    allowed = {'wk_ocp_domain', 'tls_issuer_name', 'keycloak_namespace', 'keycloak_cr_nombre',
               'keycloak_admin_secret', 'gateway_class', 'public_hosts', 'lab05_ksm_image', 'adoption_map',
               'publication_mode', 'ingress_certificate_enabled', 'ingress_domain',
               'acme_dns_zone', 'acme_route53_hosted_zone_id', 'acme_route53_region',
               'acme_secret_nombre', 'acme_cuenta_secret', 'acme_servidor',
               'aws_load_balancer_subnet_ids'}
    if not isinstance(supplied, dict) or set(supplied) - allowed:
        raise ValueError('Valores desconocidos: no se aceptan credenciales ni secretos')
    if supplied.get('gateway_class', 'istio') != 'istio':
        raise ValueError('Estas fases describen OSSM/Istio; otro proveedor requiere un componente separado')
    hostname = supplied.get('wk_ocp_domain', 'apps.cluster.example.com')
    internal = supplied.get('publication_mode', 'public') == 'internal'
    applications_requested = any([repo_url, revision, published_path])
    if applications_requested and not all([repo_url, revision, published_path]):
        raise ValueError('Applications requieren repo, revisión y path juntos; el render de componentes omite los tres')
    if supplied.get('publication_mode', 'public') not in {'public','internal'} or (internal and applications_requested and repo_url != INTERNAL_REPO):
        raise ValueError('El bundle interno requiere la URL interna exacta y no debe publicarse en Git público')
    if not internal and not hostname.endswith('.example.com') and hostname not in supplied.get('public_hosts', []):
        raise ValueError('Un hostname real requiere declaración public_hosts y revisión de publicación')
    if not re.fullmatch(r'[a-z0-9.-]+', hostname) or hostname.endswith(('.internal','.local','.localhost')):
        raise ValueError('Hostname inválido')
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        address = None
    if address is not None:
        raise ValueError('El hostname no debe ser una dirección IP')
    output = output.resolve()
    if output.exists():
        raise ValueError('Usar un directorio de salida nuevo; no sobrescribir artefactos revisados')
    common = ROOT / 'common/roles/plataforma'
    values = load(ROOT / 'ansible/inventory/group_vars/all.yml')
    values.update(load(ROOT / 'labs/lab05/roles/lab05/defaults/main.yml'))
    values.update(supplied)
    values.update(keycloak_db_password='NO_PUBLICAR', keycloak_admin_password_inicial='NO_PUBLICAR')
    phases = PHASES.copy()
    subnets = supplied.get('aws_load_balancer_subnet_ids', [])
    if not isinstance(subnets,list) or any(not isinstance(s,str) or not re.fullmatch(r'subnet-[0-9a-f]{8,17}',s) for s in subnets):
        raise ValueError('aws_load_balancer_subnet_ids debe ser una lista de IDs existentes')
    if len(subnets)!=len(set(subnets)):
        raise ValueError('No duplicar subnets')
    values['aws_load_balancer_subnet_ids'] = subnets
    if subnets:
        phases.insert(phases.index('istio')+1, 'gateway-defaults')
    ingress_enabled = supplied.get('ingress_certificate_enabled', False)
    if not isinstance(ingress_enabled, bool):
        raise ValueError('ingress_certificate_enabled debe ser booleano')
    if ingress_enabled:
        domain = supplied.get('ingress_domain', '')
        if not re.fullmatch(r'[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?',domain) or '.' not in domain:
            raise ValueError('ingress_domain explícito debe ser el spec.domain detectado externamente')
        if domain.endswith(('.internal','.local','.localhost')) or not internal and not domain.endswith('.example.com') and domain not in supplied.get('public_hosts',[]):
            raise ValueError('Dominio ingress no autorizado para publicación pública')
        for required in ['acme_dns_zone','acme_route53_hosted_zone_id','acme_route53_region']:
            if not isinstance(supplied.get(required),str) or not supplied[required]:
                raise ValueError('Falta parámetro público ACME: '+required)
        phases.append('ingress-certificate')
    manifests = {name: [] for name in phases}
    sources = {str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
               for path in [ROOT/'ansible/inventory/group_vars/all.yml',
                            ROOT/'labs/lab05/roles/lab05/defaults/main.yml']}
    def source(path):
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
        return project(path, values)
    if ingress_enabled:
        values.update(acme_issuer_nombre='cl-ingress-acme', acme_issuer_kind='Issuer',
                      acme_issuer_namespace='openshift-ingress', acme_email='',
                      dns_provider_datos={'AWS_REGION':supplied['acme_route53_region']},
                      acme_secret_nombre=supplied.get('acme_secret_nombre','acme-route53-credentials'),
                      acme_cuenta_secret=supplied.get('acme_cuenta_secret','cl-ingress-acme-account'),
                      acme_servidor=supplied.get('acme_servidor','https://acme-v02.api.letsencrypt.org/directory'))
        issuer = source(ROOT/'common/roles/acme_issuer/templates/cluster-issuer.yaml.j2')[0]
        manifests['ingress-certificate'] = [issuer]
        manifests['ingress-certificate'] += source(ROOT/'platform/kustomize/components/ingress-certificate/certificate.yaml.j2')
    for operator in values['plataforma_operadores']:
        values.update(operador=operator, plataforma_og_crear=operator['namespace'] != 'openshift-operators',
                      plataforma_operador_all_namespaces=operator.get('og_all_namespaces', False))
        for r in source(common/'templates/operador.yaml.j2'):
            if r['kind'] == 'Namespace' and r['metadata']['name'] == 'openshift-operators':
                continue
            manifests['operators'].append(r)
    istio = source(common/'templates/istio.yaml.j2')
    manifests['istio-cni'] = [r for r in istio if r['kind'] == 'IstioCNI']
    manifests['istio'] = [r for r in istio if r['kind'] == 'Istio']
    if subnets:
        defaults = ROOT/'common/roles/gateway_defaults/defaults/main.yml'
        values['gateway_defaults_name'] = load(defaults)['gateway_defaults_name']
        sources[str(defaults.relative_to(ROOT))] = hashlib.sha256(defaults.read_bytes()).hexdigest()
        values['gateway_defaults_namespace'] = manifests['istio'][0]['spec']['namespace']
        manifests['gateway-defaults'] = source(ROOT/'common/roles/gateway_defaults/templates/configmap.yaml.j2')
    for phase, filename in [('kuadrant','kuadrant'), ('cert-manager','cluster-issuer'), ('keycloak','keycloak-instancia')]:
        manifests[phase] = source(common/f'templates/{filename}.yaml.j2')
    # Todas las fases empiezan manuales; no se declara auto-heal sin resolver el handoff Lab05.
    lab05 = ROOT/'labs/lab05/roles/lab05'
    manifests['observability'] = source(lab05/'templates/plataforma-tempo.yaml.j2')
    manifests['observability'] += source(lab05/'templates/plataforma-grafana.yaml.j2')
    values['lab05_operador'] = {}
    for operator in values['lab05_operadores']:
        values['lab05_operador'] = operator
        values['lab05_og_crear'] = True
        manifests['operators'] += source(lab05/'templates/operador.yaml.j2')
    ksm = lab05/'files/kube-state-metrics-kuadrant.yaml'
    sources[str(ksm.relative_to(ROOT))] = hashlib.sha256(ksm.read_bytes()).hexdigest()
    image = supplied.get('lab05_ksm_image')
    blockers = []
    if image:
        if not re.fullmatch(r'[a-zA-Z0-9./:@_-]+', image):
            raise ValueError('Imagen KSM inválida')
        manifests['observability'].append({'apiVersion':'v1','kind':'Namespace',
                                         'metadata':{'name':values['lab05_ksm_namespace']}})
        manifests['observability'] += [r for r in yaml.safe_load_all(ksm.read_text().replace('IMAGEN_KSM',image)) if r]
    else:
        blockers.append('Falta lab05_ksm_image: debe ser la imagen del Deployment KSM del clúster, no un tag inventado.')
    # Proyectar sólo los padres: el operador configura sus hijos Authorino/plugin.
    patch_source = lab05/'tasks/plataforma_instalar.yml'
    sources[str(patch_source.relative_to(ROOT))] = hashlib.sha256(patch_source.read_bytes()).hexdigest()
    patches = []
    for task in load(patch_source):
        action = task.get('kubernetes.core.k8s', {})
        if action.get('state') != 'patched' or action.get('kind') not in {'Istio','Kuadrant'}:
            continue
        if action.get('name') not in {'default','kuadrant'}:
            continue
        context = values | task.get('vars', {})
        for key, value in list(context.items()):
            if isinstance(value,str) and '{{' in value:
                context[key] = ENV.from_string(value).render(**context)
        definition = yaml.safe_load(ENV.from_string(yaml.safe_dump(action['definition'])).render(**context))
        patch = {'apiVersion':action['api_version'], 'kind':action['kind'],
                 'metadata':{'name':action['name']}, **definition}
        if action.get('namespace'):
            patch['metadata']['namespace'] = action['namespace']
        patches.append(patch)
        if action['kind'] in {'Istio','Kuadrant'}:
            phase = 'istio' if action['kind']=='Istio' else 'kuadrant'
            merge(manifests[phase][0], definition)
    workaround_role = ROOT/'common/roles/console_plugin_configuration'
    for path in sorted(workaround_role.rglob('*.yml')):
        sources[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    runtime_actions = [{
        'action':'metrics-workload-suffix',
        'role':'console_plugin_configuration',
        'resource':{'apiVersion':'apps/v1','kind':'Deployment','namespace':'kuadrant-system','name':'kuadrant-console-plugin'},
        'ownership':'operator; excluded from Argo CD desired resources',
        'reason':'La API padre no expone METRICS_WORKLOAD_SUFFIX; workaround nativo explícito del proveedor.',
        'verify':'cd automation/ansible && ansible-playbook playbooks/console-plugin.yml',
        'apply':'cd automation/ansible && ansible-playbook playbooks/console-plugin.yml -e console_plugin_verificar_solo=false',
        'gate':'observability',
    }, {
        'action':'console-plugin-enablement',
        'role':'console_plugin_configuration',
        'resource':{'apiVersion':'operator.openshift.io/v1','kind':'Console','name':'cluster'},
        'ownership':'console operator; external precondition excluded from Argo CD desired resources',
        'reason':'Console.spec.plugins debe habilitar el plugin; un backend Ready no acredita su carga.',
        'verify':'cd automation/ansible && ansible-playbook playbooks/console-plugin.yml',
        'verification_tasks':'common/roles/console_plugin_configuration/tasks/habilitacion.yml',
        'apply':'cd automation/ansible && ansible-playbook playbooks/console-plugin.yml -e console_plugin_verificar_solo=false',
        'write_scope':'Opt-in explícito: CAS agrega sólo kuadrant-console-plugin si falta; conserva otros plugins y rechaza ownership Argo CD.',
        'gate':'observability',
        'additional_verification':'Lab01 reutiliza habilitacion.yml sin aplicar el workaround de métricas.',
    }]
    external_rbac = source(common/'templates/workshop-rbac.yaml.j2')
    external_namespaces = {}
    sources[str(IDENTITY_SOURCE.relative_to(ROOT))] = hashlib.sha256(IDENTITY_SOURCE.read_bytes()).hexdigest()
    identities = []
    persistent_resources = []
    for phase in phases:
        target = output/'components'/phase
        target.mkdir(parents=True)
        external_rbac += [r for r in manifests[phase] if r['kind'] in RBAC_KINDS]
        for resource in manifests[phase]:
            if resource['kind'] == 'Namespace':
                external_namespaces[resource['metadata']['name']] = resource
            namespace=resource['metadata'].get('namespace')
            if namespace:
                external_namespaces.setdefault(namespace,{'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace}})
            if resource['kind'] in {'Istio','IstioCNI'}:
                namespace=resource['spec']['namespace']
                external_namespaces.setdefault(namespace,{'apiVersion':'v1','kind':'Namespace','metadata':{'name':namespace}})
        safe = [clean for r in manifests[phase] if r['kind'] not in RBAC_KINDS | {'Namespace'} and (clean := sanitize(r)) is not None]
        if any(r['metadata'].get('namespace') == IDENTITY['namespace'] or r['kind'] == 'Namespace' and r['metadata']['name'] == IDENTITY['namespace'] for r in safe):
            raise ValueError('El namespace de control se instala por bootstrap, no se adopta')
        persistent_resources += safe
        for r in safe:
            identity = '|'.join([r['apiVersion'],r['kind'],r['metadata'].get('namespace',''),r['metadata']['name']])
            actual_name = supplied.get('adoption_map',{}).get(identity)
            if actual_name is not None:
                if r['kind'] not in {'OperatorGroup','Subscription'} or not re.fullmatch(r'[a-z0-9.-]+',actual_name):
                    raise ValueError('Adoption map solo admite nombres existentes OLM verificados')
                r['metadata']['name'] = actual_name
            identities.append({'phase':phase, 'apiVersion':r['apiVersion'], 'kind':r['kind'], **{k:r['metadata'][k] for k in ['name','namespace'] if k in r['metadata']}})
        (target/'manifests.yaml').write_text(yaml.safe_dump_all(safe, sort_keys=False))
        (target/'kustomization.yaml').write_text(yaml.safe_dump({'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization','resources':['manifests.yaml']}, sort_keys=False))
        descriptor = ROOT/'platform/kustomize/components'/phase/'component.yml'
        expected = load(descriptor)
        assert expected['phase'] == phase
    overlay = output/'overlays/example';overlay.mkdir(parents=True)
    (overlay/'kustomization.yaml').write_text(yaml.safe_dump({'apiVersion':'kustomize.config.k8s.io/v1beta1','kind':'Kustomization','resources':['../../components/'+p for p in phases]},sort_keys=False))
    (output/'adoption-map.json').write_text(json.dumps(identities,indent=2)+'\n')
    (output/'source-parity.json').write_text(json.dumps(sources,indent=2)+'\n')
    (output/'handoff-blockers.json').write_text(json.dumps(blockers,indent=2)+'\n')
    (output/'observability-patches.json').write_text(json.dumps(patches,indent=2)+'\n')
    (output/'runtime-actions.json').write_text(json.dumps(runtime_actions,indent=2)+'\n')
    external_preconditions = [
        {'apiVersion':'cert-manager.io/v1','kind':'ClusterIssuer','name':'letsencrypt-dns01',
         'contract':'Production ACME issuer Ready; bootstrap instructor, preserved outside desired state.'},
        {'apiVersion':'operator.openshift.io/v1alpha1','kind':'CertManager','name':'cluster',
         'contract':'DNS01 public resolver overrideArgs; full spec verified against private expectations, preserved.'},
        {'apiVersion':'v1','kind':'ConfigMap','namespace':'openshift-monitoring','name':'cluster-monitoring-config',
         'contract':'config.yaml enableUserWorkload=true; complete config data preserved outside desired state.'},
    ]
    bootstrap = output/'bootstrap';bootstrap.mkdir()
    if IDENTITY['namespace'] in external_namespaces:
        raise ValueError('El namespace de control no es bootstrap de la plataforma adoptada')
    namespace_documents=[external_namespaces[name] for name in sorted(external_namespaces)]
    (bootstrap/'external-namespaces.yaml').write_text(yaml.safe_dump_all(namespace_documents,sort_keys=False))
    external_preconditions += [{'apiVersion':'v1','kind':'Namespace','name':r['metadata']['name'],'contract':'Existing bootstrap namespace Active, UID and full normalized metadata/spec preserved; no writes.', 'canonical':r} for r in namespace_documents]
    (bootstrap/'external-rbac.yaml').write_text(yaml.safe_dump_all(external_rbac,sort_keys=False))
    external_preconditions += [{'apiVersion':r['apiVersion'],'kind':r['kind'],**{k:r['metadata'][k] for k in ('name','namespace') if k in r['metadata']},'contract':'Instructor bootstrap RBAC; full canonical rules/subjects/roleRef preserved; no controller write.', 'canonical':r} for r in external_rbac]
    (output/'platform-controller.json').write_text(json.dumps(IDENTITY,indent=2)+'\n')
    desired_keys = {(r['apiVersion'],r['kind'],r['metadata'].get('namespace',''),r['metadata']['name']) for r in persistent_resources}
    if any((r['apiVersion'],r['kind'],r.get('namespace',''),r['name']) in desired_keys for r in external_preconditions):
        raise ValueError('Un prerrequisito externo no puede declararse también como recurso GitOps; revisar propiedad antes del handoff')
    (output/'external-preconditions.json').write_text(json.dumps(external_preconditions,indent=2)+'\n')

    required_secrets = [{'phase':phase,'name':r['metadata']['name'],
                         'namespace':r['metadata'].get('namespace'),
                         'keys':sorted((r.get('data') or r.get('stringData') or {}).keys())}
                        for phase in phases for r in manifests[phase] if r['kind']=='Secret']
    if ingress_enabled:
        required_secrets.append({'phase':'ingress-certificate','name':values['acme_secret_nombre'],
                                 'namespace':'openshift-ingress','keys':['AWS_ACCESS_KEY_ID','AWS_SECRET_ACCESS_KEY']})
    (output/'required-secrets.json').write_text(json.dumps(required_secrets,indent=2)+'\n')
    if any([repo_url, revision, published_path]):
        if not all([repo_url, revision, published_path]) or not (re.fullmatch(r'https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?', repo_url) or internal and repo_url==INTERNAL_REPO):
            raise ValueError('Applications requieren repo HTTPS público, revisión y path publicado explícitos')
        if not re.fullmatch(r'[a-f0-9]{40}', revision) or revision == '0'*40 or Path(published_path).is_absolute() or '..' in Path(published_path).parts:
            raise ValueError('Revisión debe ser SHA inmutable y path relativo seguro')
        apps = output/'applications';apps.mkdir()
        for phase in phases:
            app = {'apiVersion':'argoproj.io/v1alpha1','kind':'Application','metadata':{'name':IDENTITY['name']+'-'+phase,'namespace':IDENTITY['namespace'],'labels':LABEL},'spec':{'project':IDENTITY['name'],'source':{'repoURL':repo_url,'targetRevision':revision,'path':published_path.rstrip('/')+'/components/'+phase},'destination':{'server':'https://kubernetes.default.svc'},'syncPolicy':{'syncOptions':['FailOnSharedResource=true','ServerSideApply=true','ClientSideApplyMigration=false']}}}
            (apps/(phase+'.yaml')).write_text(yaml.safe_dump(app,sort_keys=False))
        access = output/'access';access.mkdir()
        (access/'project-and-rbac.yaml').write_text(yaml.safe_dump_all(access_documents(persistent_resources,repo_url,set(external_namespaces)),sort_keys=False))
    print(f'Render: {len(identities)} recursos; manual, sin sync. Handoff bloqueado: {len(blockers)} requisito pendiente.')
    return identities


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--values',type=Path,default=ROOT/'platform/kustomize/overlays/example/values.yml')
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--repo-url');parser.add_argument('--revision');parser.add_argument('--published-path')
    args=parser.parse_args()
    render(args.values,args.output,args.repo_url,args.revision,args.published_path)
