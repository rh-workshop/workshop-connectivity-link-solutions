"""Excepción HTTPS del CCM: únicamente preserve_client_ip.enabled; sin adopción TG."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess


def call(args):
    return json.loads(subprocess.run(args, check=True, capture_output=True, text=True).stdout)


def validate(config, account, service, balancer, listeners, group, tags, attributes):
    if account != config['account_id']:
        raise ValueError('Cuenta AWS distinta')
    metadata = service.get('metadata', {})
    if metadata.get('uid') != config['service_uid'] or metadata.get('deletionTimestamp'):
        raise ValueError('Service recreado o en eliminación')
    annotations = metadata.get('annotations', {})
    if 'service.beta.kubernetes.io/aws-load-balancer-target-group-attributes' in annotations:
        raise ValueError('CCM posee atributos mediante anotación; conflicto de configuración')
    if (balancer['LoadBalancerArn'] != config['load_balancer_arn'] or
            balancer['Type'] != 'network' or balancer['State']['Code'] != 'active'):
        raise ValueError('NLB distinto o inactivo')
    https = [x for x in listeners if x.get('Port') == 443]
    if len(https) != 1 or https[0]['Protocol'] != 'TCP':
        raise ValueError('Listener HTTPS inesperado')
    actions = https[0]['DefaultActions']
    if len(actions) != 1 or actions[0].get('Type') != 'forward' or actions[0].get('TargetGroupArn') != config['target_group_arn']:
        raise ValueError('HTTPS ya no apunta al TG revisado')
    forwarded = actions[0].get('ForwardConfig', {}).get('TargetGroups', [])
    if forwarded and forwarded != [{'TargetGroupArn': config['target_group_arn']}]:
        raise ValueError('ForwardConfig incluye otros destinos/pesos no revisados')
    for listener in listeners:
        if listener['Port'] == 443:
            continue
        for action in listener.get('DefaultActions', []):
            referenced = {action.get('TargetGroupArn')}
            referenced.update(item.get('TargetGroupArn') for item in action.get('ForwardConfig', {}).get('TargetGroups', []))
            if config['target_group_arn'] in referenced:
                raise ValueError('TG HTTPS compartido con otro listener; cambio no es exclusivo de 443')
    if (group['TargetGroupArn'] != config['target_group_arn'] or group['Protocol'] != 'TCP' or
            group['TargetType'] != 'instance' or group['LoadBalancerArns'] != [config['load_balancer_arn']]):
        raise ValueError('TG recreado o tipo/configuración distinto')
    if tags.get('kubernetes.io/service-name') != 'openshift-ingress/router-default' or tags.get('kubernetes.io/cluster/' + config['cluster_id']) != 'owned':
        raise ValueError('TG no pertenece al Service/clúster esperado')
    hostnames = [x.get('hostname') for x in service.get('status', {}).get('loadBalancer', {}).get('ingress', [])]
    if balancer['DNSName'] not in hostnames:
        raise ValueError('Service ya apunta a otro NLB')
    if attributes.get('proxy_protocol_v2.enabled') != 'false' or attributes.get('preserve_client_ip.enabled') not in ('true', 'false'):
        raise ValueError('Proxy protocol/atributos inesperados')


def boolean(config, name):
    if type(config.get(name)) is not bool:
        raise ValueError('Booleano real requerido: ' + name)
    return config[name]


def private_write(path, data):
    path = Path(path).expanduser()
    repository = Path(__file__).resolve().parents[4]
    if not path.is_absolute() or path.resolve().is_relative_to(repository):
        raise ValueError('Informe/snapshot debe estar fuera del repositorio')
    if not path.parent.is_dir() or path.parent.stat().st_mode & 0o077:
        raise ValueError('Directorio privado requerido (0700)')
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'w') as stream:
        json.dump(data, stream, indent=2)


def digest(data):
    return hashlib.sha256(json.dumps(data, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def run(config, mode, report_path=None, caller=call):
    if mode not in ('verify', 'apply'):
        raise ValueError('Modo desconocido')
    expected_current = 'true' if boolean(config, 'expected_current_preserve_client_ip') else 'false'
    for name in ['preserve_client_ip', 'ip_audit_approved', 'ccm_ownership_verified']:
        if name in config:
            boolean(config, name)
    if mode == 'apply':
        if not boolean(config, 'ip_audit_approved') or not boolean(config, 'ccm_ownership_verified'):
            raise ValueError('Faltan revisiones IP/CCM')
        boolean(config, 'preserve_client_ip')
    aws = ['aws', '--region', config['region'], '--output', 'json']
    def api(operation, *args):
        return caller(aws + ['elbv2', operation, *args])
    def attributes(arn):
        return {x['Key']: x['Value'] for x in api('describe-target-group-attributes', '--target-group-arn', arn)['Attributes']}
    def inspect(expected_value):
        account = caller(aws + ['sts', 'get-caller-identity'])['Account']
        service = caller(['oc', 'get', 'service', 'router-default', '-n', 'openshift-ingress', '-o', 'json'])
        lb = api('describe-load-balancers', '--load-balancer-arns', config['load_balancer_arn'])['LoadBalancers'][0]
        listeners = api('describe-listeners', '--load-balancer-arn', config['load_balancer_arn'])['Listeners']
        groups = api('describe-target-groups', '--load-balancer-arn', config['load_balancer_arn'])['TargetGroups']
        groups_by_arn = {x['TargetGroupArn']: x for x in groups}
        tg = groups_by_arn[config['target_group_arn']]
        arns = [config['load_balancer_arn']] + sorted(groups_by_arn)
        tag_entries = api('describe-tags', '--resource-arns', *arns)['TagDescriptions']
        tags = {x['ResourceArn']: {t['Key']: t['Value'] for t in x['Tags']} for x in tag_entries}
        attrs = {arn: attributes(arn) for arn in groups_by_arn}
        validate(config, account, service, lb, listeners, tg, tags[config['target_group_arn']], attrs[config['target_group_arn']])
        for arn in arns:
            if tags[arn].get('kubernetes.io/service-name') != 'openshift-ingress/router-default' or tags[arn].get('kubernetes.io/cluster/' + config['cluster_id']) != 'owned':
                raise ValueError('Propiedad NLB/TG distinta')
        if attrs[config['target_group_arn']]['preserve_client_ip.enabled'] != expected_value:
            raise ValueError('preserve_client_ip difiere del baseline explícito')
        return {'service_uid': service['metadata']['uid'], 'service_spec': service['spec'],
                'service_annotations': service['metadata'].get('annotations', {}),
                'listeners': sorted(listeners, key=lambda item: item['Port']),
                'load_balancer': lb, 'load_balancer_attributes': api('describe-load-balancer-attributes', '--load-balancer-arn', config['load_balancer_arn']),
                'groups': groups_by_arn, 'tags': tags, 'attributes': attrs,
                'registered_targets': {arn: sorted(
                    [item['Target'] for item in api('describe-target-health', '--target-group-arn', arn)['TargetHealthDescriptions']],
                    key=lambda item: json.dumps(item, sort_keys=True)) for arn in groups_by_arn}}
    helper_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    before = inspect(expected_current)
    identity_keys = ['account_id', 'region', 'load_balancer_arn', 'target_group_arn', 'service_uid', 'cluster_id', 'expected_current_preserve_client_ip']
    identity = {key: config[key] for key in identity_keys}
    review = {'mode': 'verify-only-no-approval', 'helper_sha256': helper_hash, 'identity': identity,
              'observed_sha256': digest(before), 'observed': before}
    if mode == 'verify':
        private_write(report_path, review)
        return review
    approved = Path(config['approved_review_path'])
    if not approved.is_absolute() or approved.resolve().is_relative_to(Path(__file__).resolve().parents[4]):
        raise ValueError('Review aprobado debe estar fuera del repositorio')
    if approved.stat().st_mode & 0o077:
        raise ValueError('Review aprobado debe ser privado (0600)')
    approved_bytes = approved.read_bytes()
    if hashlib.sha256(approved_bytes).hexdigest() != config['approved_review_sha256']:
        raise ValueError('Artefacto aprobado cambió')
    baseline = json.loads(approved_bytes)
    if baseline != review:
        raise ValueError('Helper/configuración/baseline distinto del informe revisado')
    private_write(config['snapshot_path'], {'configuration': config, 'before': before, 'review_sha256': config['approved_review_sha256']})
    if inspect(expected_current) != before:
        raise ValueError('Drift previo a modificación: no se cambió nada')
    value = 'true' if config['preserve_client_ip'] else 'false'
    api('modify-target-group-attributes', '--target-group-arn', config['target_group_arn'],
        '--attributes', f'Key=preserve_client_ip.enabled,Value={value}')
    expected = json.loads(json.dumps(before))
    expected['attributes'][config['target_group_arn']]['preserve_client_ip.enabled'] = value
    if inspect(value) != expected:
        raise ValueError('Estado posterior distinto del único delta autorizado; revisar snapshot y rollback')
    return {'result': 'sole-https-attribute-change-verified'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['verify', 'apply'], default='verify')
    parser.add_argument('--config', type=Path)
    parser.add_argument('--report', type=Path)
    args = parser.parse_args()
    if args.mode == 'verify' and args.report is None:
        parser.error('--report privado nuevo requerido para verify')
    config = json.loads(args.config.read_text() if args.config else os.environ['WK_HAIRPIN_CONFIG'])
    run(config, args.mode, args.report)
    print('Verificación completada sin imprimir configuración privada.')


if __name__ == '__main__':
    main()
