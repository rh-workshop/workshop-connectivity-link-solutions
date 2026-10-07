"""Comprueba una operación Argo exacta antes del gate nativo; sólo lectura."""
import argparse
from pathlib import Path
import re
import sys
import yaml

sys.path.insert(0,str(Path(__file__).resolve().parent))
import check_adoption as G


def identity(resource,manifest=False):
    metadata=resource.get('metadata',{}) if manifest else resource
    version=resource.get('apiVersion','')
    group=version.split('/')[0] if '/' in version else ''
    return (group if manifest else resource.get('group',''),resource['kind'],metadata.get('namespace',''),metadata['name'])


def validate(application,resources,revision,operation_id,application_name):
    if not re.fullmatch('[0-9a-f]{40}',revision) or revision=='0'*40:
        raise ValueError('invalid_immutable_revision')
    if not re.fullmatch('[A-Za-z0-9_.:-]{1,128}',operation_id):raise ValueError('invalid_operation_id')
    if not re.fullmatch(re.escape(G.IDENTITY['name'])+'-[a-z0-9-]+',application_name):raise ValueError('invalid_platform_application')
    if application.get('apiVersion')!='argoproj.io/v1alpha1' or application.get('kind')!='Application' or application.get('metadata',{}).get('namespace')!=G.IDENTITY['namespace'] or application['metadata'].get('name')!=application_name:
        raise ValueError('application_identity_mismatch')
    metadata=application['metadata'];spec=application.get('spec',{});status=application.get('status',{})
    if metadata.get('deletionTimestamp') or not metadata.get('uid'):raise ValueError('application_not_active')
    if metadata.get('finalizers') or spec.get('syncPolicy',{}).get('automated') is not None or application.get('operation') is not None:
        raise ValueError('application_not_manual_or_operation_active')
    if spec.get('source',{}).get('targetRevision')!=revision or spec.get('sources'):
        raise ValueError('application_target_revision_mismatch')
    if status.get('sync',{}).get('status')!='Synced' or status['sync'].get('revision')!=revision:
        raise ValueError('application_not_synced_at_revision')
    if any(str(condition.get('type','')).endswith('Error') for condition in status.get('conditions',[])):
        raise ValueError('application_error_condition')
    operation=status.get('operationState',{})
    if operation.get('phase')!='Succeeded':raise ValueError('operation_not_succeeded')
    requested=operation.get('operation',{})
    if requested.get('info')!=[{'name':'validation-run','value':operation_id}]:raise ValueError('operation_id_mismatch')
    if requested.get('sync',{}).get('prune') or requested.get('sync',{}).get('revision')!=revision:
        raise ValueError('operation_revision_or_prune_mismatch')
    result=operation.get('syncResult',{})
    if result.get('revision')!=revision:raise ValueError('operation_result_revision_mismatch')
    if not resources or any(r['kind'] in G.RBAC_KINDS|{'Namespace','Secret','List'} for r in resources):
        raise ValueError('invalid_phase_manifest')
    expected={identity(r,True):r for r in resources}
    if len(expected)!=len(resources):raise ValueError('duplicate_phase_identity')
    records=[]
    for label,actual in [('operation_result',result.get('resources')),('application_status',status.get('resources'))]:
        if not isinstance(actual,list):raise ValueError('missing_'+label+'_resources')
        keys=[identity(r) for r in actual]
        if len(set(keys))!=len(keys) or set(keys)!=set(expected):raise ValueError(label+'_resource_set_mismatch')
        for r in actual:
            if r.get('status')!='Synced' or r.get('hookPhase') in {'Failed','Error'} or r.get('requiresPruning'):
                raise ValueError(label+'_resource_not_synced')
            source=expected[identity(r)];version=source['apiVersion'].split('/')[-1]
            if 'version' in r and r['version']!=version:raise ValueError(label+'_resource_version_mismatch')
            if 'apiVersion' in r and r['apiVersion']!=source['apiVersion']:raise ValueError(label+'_resource_version_mismatch')
        if label=='operation_result':records=[{'group':k[0],'kind':k[1],'namespace':k[2],'name':k[3],'status':'Synced'} for k in sorted(keys)]
    return {'ok':True,'application':application_name,'namespace':G.IDENTITY['namespace'],'application_uid':metadata['uid'],
            'revision':revision,'operation_id':operation_id,'phase':'Succeeded','resource_count':len(records),'resources':records,
            'proof':'Exact completed manual operation and resource sets; native readiness remains required.'}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--application',required=True);parser.add_argument('--namespace',default=G.IDENTITY['namespace'])
    parser.add_argument('--revision',required=True);parser.add_argument('--operation-id',required=True)
    parser.add_argument('--manifest',type=Path,required=True);parser.add_argument('--report',type=Path,required=True)
    args=parser.parse_args()
    try:
        if args.namespace!=G.IDENTITY['namespace']:raise ValueError('noncanonical_application_namespace')
        if args.application!=G.IDENTITY['name']+'-'+args.manifest.parent.name:raise ValueError('application_phase_manifest_mismatch')
        resources=list(yaml.safe_load_all(args.manifest.read_text()))
        application=G.Oc().get({'apiVersion':'argoproj.io/v1alpha1','kind':'Application','metadata':{'namespace':args.namespace,'name':args.application}},impersonate=False)
        report=validate(application,resources,args.revision,args.operation_id,args.application)
    except (ValueError,KeyError,TypeError,OSError,yaml.YAMLError,G.subprocess.TimeoutExpired) as error:
        code=str(error) if isinstance(error,ValueError) and re.fullmatch('[a-z_]+',str(error)) else 'application_sync_check_failed'
        report={'ok':False,'errors':[code]}
    G.private_report(args.report,report)
    print('PASS: operación exacta completada; ejecutar gate nativo' if report['ok'] else 'FAIL: sync no acreditado; revisar informe privado')
    return 0 if report['ok'] else 1


if __name__=='__main__':sys.exit(main())
