"""Scope de cache local: CAS parcial y respaldo sin credenciales; nunca crea Secrets."""
import base64
import hashlib
import json
import os
from pathlib import Path
import re

SCOPE = ('namespaces', 'clusterResources')


def private_path(value):
    path = Path(value).expanduser()
    if not value or not path.is_absolute() or path.is_symlink():
        raise ValueError('private_path_required')
    if any(parent.is_symlink() for parent in path.parents):
        raise ValueError('private_path_symlink')
    path = path.resolve()
    if any((parent/'.git').exists() for parent in (path.parent, *path.parents)):
        raise ValueError('private_path_inside_git')
    return path


def decode(data, key):
    try:
        return base64.b64decode(data[key], validate=True).decode('utf-8')
    except (KeyError, ValueError, UnicodeDecodeError, TypeError):
        raise ValueError('invalid_cluster_scope_encoding') from None


def write_backup(value, document):
    backup = private_path(value)
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as output:
        json.dump(document, output, sort_keys=True)
        output.write('\n')
    os.chmod(backup, 0o600)


def validate(args):
    identity = args['identity']
    render = private_path(args['render_dir'])
    external = json.loads((render/'external-preconditions.json').read_text())
    expected = {item['name'] for item in external if item.get('kind') == 'Namespace'
                and item.get('apiVersion') == 'v1'} | {identity['namespace']}
    supplied = args['namespaces']
    if (not isinstance(supplied, list) or not supplied or not all(isinstance(value, str) for value in supplied)
            or len(supplied) != len(set(supplied))
            or set(supplied) != expected or any(not isinstance(value, str) or not
            re.fullmatch(r'[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?', value) for value in supplied)):
        raise ValueError('namespace_set_mismatch')
    if args['operation'] == 'plan':
        for app in args.get('applications', []):
            if app.get('operation') is not None or app.get('status', {}).get(
                    'operationState', {}).get('phase') in ('Pending', 'Running', 'Terminating'):
                raise ValueError('application_operation_active')
    local = [secret for secret in args['secrets']
             if decode(secret.get('data', {}), 'server') == 'https://kubernetes.default.svc']
    if len(local) != 1:
        raise ValueError('local_cluster_connection_not_unique')
    secret = local[0]
    meta = secret['metadata']
    owners = meta.get('ownerReferences', [])
    expected_uid = args.get('expected_secret_uid', '')
    if (not expected_uid or meta.get('uid') != expected_uid
            or meta.get('name') != identity['name']+'-default-cluster-config'
            or meta.get('namespace') != identity['namespace']
            or meta.get('deletionTimestamp') is not None
            or not meta.get('resourceVersion')
            or not any(owner.get('kind') == 'ArgoCD' and owner.get('name') == identity['name']
                       and owner.get('apiVersion') == 'argoproj.io/v1beta1'
                       and owner.get('uid') == args['instance_uid'] for owner in owners)):
        raise ValueError('foreign_cluster_connection')
    data = secret['data']
    other_hash = hashlib.sha256(json.dumps({key:value for key,value in data.items()
        if key not in SCOPE}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
    if args.get('expected_other_data_hash') and other_hash != args['expected_other_data_hash']:
        raise ValueError('other_cluster_data_changed')
    namespaces = decode(data, 'namespaces').split(',') if 'namespaces' in data else []
    correct = (len(namespaces) == len(set(namespaces)) and set(namespaces) == expected
               and 'clusterResources' in data and decode(data, 'clusterResources') == 'true')
    if args['operation'] == 'verificar' and not correct:
        raise ValueError('cluster_scope_not_configured')
    patch = []
    if not correct:
        patch = [{'op':'test','path':'/metadata/uid','value':meta['uid']},
                 {'op':'test','path':'/metadata/resourceVersion','value':meta['resourceVersion']}]
        desired = {'namespaces':','.join(sorted(expected)), 'clusterResources':'true'}
        for key,value in desired.items():
            encoded = base64.b64encode(value.encode()).decode()
            if data.get(key) == encoded:
                continue
            if key in data:
                patch.append({'op':'test','path':'/data/'+key,'value':data[key]})
            patch.append({'op':'replace' if key in data else 'add',
                          'path':'/data/'+key,'value':encoded})
    return secret, other_hash, patch


def execute(args):
    if args['operation'] == 'plan_controller':
        instance = args['instance']
        meta = instance['metadata']
        identity = args['identity']
        if (meta.get('uid') != args['instance_uid'] or not meta.get('resourceVersion')
                or meta.get('name') != identity['name'] or meta.get('namespace') != identity['namespace']
                or instance.get('kind') != 'ArgoCD' or instance.get('apiVersion') != 'argoproj.io/v1beta1'
                or not args.get('owned_labels') or any(meta.get('labels', {}).get(key) != value
                                                      for key,value in args['owned_labels'].items())
                or meta.get('deletionTimestamp') is not None):
            raise ValueError('foreign_controller')
        for app in args.get('applications', []):
            if app.get('operation') is not None or app.get('status', {}).get('operationState', {}).get('phase') in ('Pending', 'Running', 'Terminating'):
                raise ValueError('application_operation_active')
        old = instance['spec']['controller']['respectRBAC']
        if old not in ('strict', 'normal'):
            raise ValueError('unexpected_controller_mode')
        patch = []
        if old != 'normal':
            document = {'instance_uid':meta['uid'], 'resource_version':meta['resourceVersion'],
                        'name':meta['name'], 'namespace':meta['namespace'], 'respectRBAC':old}
            write_backup(args['backup_path'], document)
            patch = [{'op':'test','path':'/metadata/uid','value':meta['uid']},
                     {'op':'test','path':'/metadata/resourceVersion','value':meta['resourceVersion']},
                     {'op':'test','path':'/spec/controller/respectRBAC','value':'strict'},
                     {'op':'replace','path':'/spec/controller/respectRBAC','value':'normal'}]
        return {'changed':False, 'patch':patch}
    if args['operation'] not in ('plan', 'verificar'):
        raise ValueError('invalid_operation')
    secret, other_hash, patch = validate(args)
    if args['operation'] == 'plan':
        document = {'secret_uid':secret['metadata']['uid'],
                    'resource_version':secret['metadata']['resourceVersion'],
                    'namespace':secret['metadata']['namespace'], 'name':secret['metadata']['name'],
                    'scope':{key:secret['data'].get(key) for key in SCOPE}}
        # Exclusivo: nunca reescribir un respaldo previo ni guardar token/config/server.
        write_backup(args['backup_path'], document)
    return {'changed':False, 'patch':patch, 'other_data_hash':other_hash}


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(no_log=True, argument_spec={
        'operation':{'type':'str','required':True},
        'instance':{'type':'dict','default':{}},
        'owned_labels':{'type':'dict','default':{}},
        'identity':{'type':'dict','required':True},
        'instance_uid':{'type':'str','required':True},
        'expected_secret_uid':{'type':'str','default':''},
        'secrets':{'type':'list','elements':'dict','default':[]},
        'applications':{'type':'list','elements':'dict','default':[]},
        'render_dir':{'type':'str','default':''},
        'namespaces':{'type':'list','elements':'str','default':[]},
        'backup_path':{'type':'str','default':''},
        'expected_other_data_hash':{'type':'str','default':''},
    })
    try:
        module.exit_json(invocation={}, _ansible_no_log=True, **execute(module.params))
    except Exception as error:
        # Sólo clase/código conocido, nunca objetos Secret ni mensajes de I/O privados.
        code = str(error) if isinstance(error, ValueError) and re.fullmatch(r'[a-z_]+', str(error)) else type(error).__name__
        module.fail_json(invocation={}, _ansible_no_log=True, msg='cluster_scope_rejected:'+code)


if __name__ == '__main__':
    main()
