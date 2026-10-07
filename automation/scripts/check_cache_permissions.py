"""Preflight único de cache: can-i list/watch y LIST limitado, sin cuerpos en evidencia."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import sys
import yaml
sys.path.insert(0,str(Path(__file__).resolve().parent))
import check_adoption as G


def descriptors(resources,client):
    result={};discovery={}
    for resource in resources:
        if resource['kind'] in G.RBAC_KINDS | {'Namespace','Secret','List'}:
            raise ValueError('external_or_sensitive_cache_kind')
        if not resource['metadata'].get('namespace'):continue
        version=resource['apiVersion']
        if version not in discovery:
            discovery[version]=client.run(['get','--raw','/apis/'+version if '/' in version else '/api/'+version])
        found=[r for r in discovery[version].get('resources',[]) if r.get('kind')==resource['kind'] and '/' not in r.get('name','')]
        if len(found)!=1 or found[0].get('namespaced') is not True or found[0]['name']=='secrets':
            raise ValueError('cache_resource_discovery_mismatch')
        item={'apiVersion':version,'kind':resource['kind'],'resource':found[0]['name'],'group':version.split('/')[0] if '/' in version else ''}
        result[(version,resource['kind'])]=item
    return [result[k] for k in sorted(result)]


def probe(item,namespace,client):
    record=item|{'namespace':namespace,'errors':[],'can_list':False,'can_watch':False,'listed_count':None}
    try:
        api_resource=item['resource']+('.'+item['group'] if item['group'] else '')
        record['can_list']=client.can_i('list',api_resource,namespace)
        record['can_watch']=client.can_i('watch',api_resource,namespace)
        if not record['can_list'] or not record['can_watch']:raise ValueError('cache_collection_permission_denied')
        path=('/apis/'+item['apiVersion'] if item['group'] else '/api/'+item['apiVersion'])+'/namespaces/'+namespace+'/'+item['resource']+'?limit=1'
        response=client.run(['get','--raw',path])
        items=response.get('items')
        typed=response.get('kind')==item['kind']+'List'
        if response.get('kind') not in {'List',item['kind']+'List'} or not isinstance(items,list) or len(items)>1 or (typed and response.get('apiVersion')!=item['apiVersion']):
            raise ValueError('invalid_limited_cache_collection')
        # Una lista tipada puede omitir TypeMeta en sus items; su GVK exacto lo aporta.
        if any(not isinstance(r,dict) or
               (r.get('apiVersion',item['apiVersion'] if typed else None)!=item['apiVersion']) or
               (r.get('kind',item['kind'] if typed else None)!=item['kind']) or
               not isinstance(r.get('metadata'),dict) or
               r['metadata'].get('namespace')!=namespace or
               not isinstance(r['metadata'].get('name'),str) or not r['metadata']['name'] or
               not isinstance(r['metadata'].get('uid'),str) or not r['metadata']['uid'] for r in items):
            raise ValueError('cache_list_item_identity_mismatch')
        record['listed_count']=len(items)  # Nunca cuerpos, nombres ni valores.
    except (ValueError,KeyError,TypeError,OSError,G.subprocess.TimeoutExpired) as e:
        record['errors']=[str(e) if isinstance(e,ValueError) and G.re.fullmatch('[a-z_]+',str(e)) else 'cache_probe_failed']
    return record


def matrix(resources,namespaces,client,workers=1):
    if not 1<=workers<=4:raise ValueError('cache_probe_workers_out_of_range')
    if any(not isinstance(n,str) or not G.re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?',n) for n in namespaces):
        raise ValueError('cache_namespace_invalid')
    types=descriptors(resources,client)
    if not types:raise ValueError('no_namespaced_cache_types')
    pairs=[(item,namespace) for item in types for namespace in sorted(set(namespaces)|{G.IDENTITY['namespace']})]
    with ThreadPoolExecutor(max_workers=workers) as executor:
        records=list(executor.map(lambda pair:probe(*pair,client),pairs))
    return {'ok':not any(r['errors'] for r in records),'kind_version_count':len(types),
            'namespace_count':len(set(namespaces)|{G.IDENTITY['namespace']}),'pair_count':len(records),
            'records':records,'impersonation':{'user':G.SA,'groups':G.GROUPS},
            'proof':'can-i list/watch plus API LIST limit=1; no item bodies recorded'}


def audit(folder,expected,client,workers=1):
    resources=G.desired(folder)
    if G.digest(resources)!=expected.get('bundle_sha256') or G.applications_digest(folder)!=expected.get('applications_sha256'):
        raise ValueError('cache_source_digests_mismatch')
    cluster=client.get({'apiVersion':'v1','kind':'Namespace','metadata':{'name':'kube-system'}},impersonate=False)
    if cluster['metadata'].get('uid')!=expected.get('cluster_uid'):raise ValueError('cluster_uid_mismatch')
    namespaces={d['name'] for d in json.loads((folder/'external-preconditions.json').read_text()) if d['kind']=='Namespace'}
    negatives=G.controller_guard(expected,client,namespaces)
    configuration=G.cluster_configuration_guard(expected,client,namespaces)
    tracking=G.tracking_configuration(expected,client)
    report=matrix(resources,namespaces,client,workers)
    if G.cluster_configuration_guard(expected,client,namespaces)!=configuration or G.normalize(tracking)!=G.normalize(client.get(tracking,impersonate=False)):
        raise ValueError('cache_configuration_changed_during_preflight')
    report.update(cluster_uid=expected['cluster_uid'],bundle_sha256=expected['bundle_sha256'],applications_sha256=expected['applications_sha256'],
                  controller=expected['controller'],negative_permission_baseline=negatives,connection_contract=configuration,respect_rbac='normal')
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--render-dir',type=Path,required=True);parser.add_argument('--expected',type=Path,required=True)
    parser.add_argument('--report',type=Path,required=True);parser.add_argument('--workers',type=int,choices=range(1,5),default=1)
    args=parser.parse_args()
    try:report=audit(args.render_dir,G.private_expectations(args.expected),G.Oc(),args.workers)
    except (ValueError,KeyError,OSError,TypeError,yaml.YAMLError,G.subprocess.TimeoutExpired) as error:
        code=str(error) if isinstance(error,ValueError) and G.re.fullmatch('[a-z_]+',str(error)) else 'cache_preflight_failed'
        report={'ok':False,'errors':[code]}
    G.private_report(args.report,report)
    print('PASS: cache finito autorizado y LIST comprobado' if report['ok'] else 'FAIL: revisar evidencia privada; sin cambios')
    return 0 if report['ok'] else 1


if __name__=='__main__':sys.exit(main())
