import copy
import importlib.util
from pathlib import Path
import unittest
import tempfile
import json
import hashlib

spec = importlib.util.spec_from_file_location('hairpin_configure', Path(__file__).resolve().parents[1] / 'configure.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class Guards(unittest.TestCase):
    def setUp(self):
        self.config = dict(account_id='123456789012', load_balancer_arn='lb', target_group_arn='tg', service_uid='uid', cluster_id='cluster', ip_audit_approved=True, ccm_ownership_verified=True)
        self.args = [self.config, '123456789012', {'metadata': {'uid': 'uid'}, 'status': {'loadBalancer': {'ingress': [{'hostname': 'nlb.example'}]}}}, {'LoadBalancerArn': 'lb', 'Type': 'network', 'State': {'Code': 'active'}, 'DNSName': 'nlb.example'}, [{'Port': 443, 'Protocol': 'TCP', 'DefaultActions': [{'Type': 'forward', 'TargetGroupArn': 'tg', 'ForwardConfig': {'TargetGroups': [{'TargetGroupArn': 'tg'}]}}]}], {'TargetGroupArn': 'tg', 'Protocol': 'TCP', 'TargetType': 'instance', 'LoadBalancerArns': ['lb']}, {'kubernetes.io/service-name': 'openshift-ingress/router-default', 'kubernetes.io/cluster/cluster': 'owned'}, {'proxy_protocol_v2.enabled': 'false', 'preserve_client_ip.enabled': 'true'}]

    def test_actual_forward_config_and_rollback_false_state(self):
        module.validate(*self.args)

    def test_http_distinct_and_shared_listener_rejected(self):
        self.args[4].append({'Port': 80, 'Protocol': 'TCP', 'DefaultActions': [{'Type': 'forward', 'TargetGroupArn': 'http', 'ForwardConfig': {'TargetGroups': [{'TargetGroupArn': 'http'}]}}]})
        module.validate(*self.args)
        for port, direct in [(80, True), (80, False), (8443, False)]:
            with self.subTest(port=port, direct=direct):
                args = copy.deepcopy(self.args)
                action = {'Type': 'forward', 'TargetGroupArn': 'tg'} if direct else {'Type': 'forward', 'ForwardConfig': {'TargetGroups': [{'TargetGroupArn': 'tg'}]}}
                args[4][1] = {'Port': port, 'Protocol': 'TCP', 'DefaultActions': [action]}
                with self.assertRaises(ValueError): module.validate(*args)
        self.args[-1]['preserve_client_ip.enabled'] = 'false'
        module.validate(*self.args)

    def test_recreated_service_tg_account_and_missing_review(self):
        variants = [(1, None, '000000000000'), (2, ('metadata', 'uid'), 'new'), (5, ('TargetGroupArn',), 'replacement')]
        for position, path, value in variants:
            with self.subTest(position=position, path=path):
                args = copy.deepcopy(self.args)
                if path:
                    obj = args[position]
                    for key in path[:-1]:
                        obj = obj[key]
                    obj[path[-1]] = value
                else:
                    args[position] = value
                with self.assertRaises(ValueError):
                    module.validate(*args)

    def test_annotation_owner_proxy_protocol_and_other_forward_target(self):
        for case in ['annotation', 'proxy', 'target', 'owner', 'dns']:
            with self.subTest(case=case):
                args = copy.deepcopy(self.args)
                if case == 'annotation':
                    args[2]['metadata']['annotations'] = {'service.beta.kubernetes.io/aws-load-balancer-target-group-attributes': ''}
                elif case == 'proxy':
                    args[-1]['proxy_protocol_v2.enabled'] = 'true'
                elif case == 'target':
                    args[4][0]['DefaultActions'][0]['ForwardConfig']['TargetGroups'].append({'TargetGroupArn': 'other'})
                elif case == 'owner':
                    args[6]['kubernetes.io/service-name'] = 'different/service'
                else:
                    args[2]['status']['loadBalancer']['ingress'][0]['hostname'] = 'new-lb'
                with self.assertRaises(ValueError):
                    module.validate(*args)


class Execution(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='hairpin-offline-')
        self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name)
        base = Guards(); base.setUp()
        self.args = base.args
        self.config = dict(base.config, region='us-east-2', expected_current_preserve_client_ip=True,
                           preserve_client_ip=False, snapshot_path=str(self.directory/'snapshot.json'))
        self.current = 'true'
        self.writes = []
        self.groups = [self.args[5], dict(self.args[5], TargetGroupArn='http', Port=30080)]

    def caller(self, args):
        if args[0] == 'oc':
            return dict(self.args[2], spec={'ports': [{'port': 443, 'nodePort': 30443}, {'port': 80, 'nodePort': 30080}]})
        op = args[6]
        if op == 'get-caller-identity': return {'Account': self.args[1]}
        if op == 'describe-load-balancers': return {'LoadBalancers': [self.args[3]]}
        if op == 'describe-listeners': return {'Listeners': self.args[4]}
        if op == 'describe-target-groups': return {'TargetGroups': self.groups}
        if op == 'describe-tags': return {'TagDescriptions': [{'ResourceArn': arn, 'Tags': [{'Key': k, 'Value': v} for k,v in self.args[6].items()]} for arn in ['lb', 'tg', 'http']]}
        if op == 'describe-target-group-attributes':
            arn = args[-1]
            value = self.current if arn == 'tg' else 'true'
            return {'Attributes': [{'Key': 'preserve_client_ip.enabled', 'Value': value}, {'Key': 'proxy_protocol_v2.enabled', 'Value': 'false'}]}
        if op == 'describe-load-balancer-attributes': return {'Attributes': [{'Key': 'load_balancing.cross_zone.enabled', 'Value': 'false'}]}
        if op == 'describe-target-health': return {'TargetHealthDescriptions': [{'Target': {'Id': 'instance', 'Port': 30443}}]}
        if op == 'modify-target-group-attributes':
            self.writes.append(args)
            self.current = args[-1].split('Value=')[1]
            return {}
        raise AssertionError(args)

    def review(self):
        path = self.directory/'review.json'
        module.run(self.config, 'verify', path, self.caller)
        self.config.update(approved_review_path=str(path), approved_review_sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        return path

    def test_verify_without_approval_and_apply_only_one_attribute(self):
        self.config.update(ip_audit_approved=False, ccm_ownership_verified=False)
        path = self.review()
        self.assertEqual(self.writes, [])
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError): module.run(self.config, 'apply', caller=self.caller)
        self.config.update(ip_audit_approved=True, ccm_ownership_verified=True)
        module.run(self.config, 'apply', caller=self.caller)
        self.assertEqual(len(self.writes), 1)
        self.assertEqual(self.writes[0][-4:], ['--target-group-arn', 'tg', '--attributes', 'Key=preserve_client_ip.enabled,Value=false'])

    def test_strings_are_not_boolean_approvals_or_baselines(self):
        for key in ['expected_current_preserve_client_ip', 'preserve_client_ip', 'ip_audit_approved', 'ccm_ownership_verified']:
            with self.subTest(key=key):
                config = dict(self.config, **{key: 'false'})
                with self.assertRaises(ValueError): module.run(config, 'apply', caller=self.caller)
        self.assertEqual(self.writes, [])

    def test_baseline_drift_and_changed_http_configuration_block(self):
        self.review()
        self.current = 'false'
        with self.assertRaises(ValueError): module.run(self.config, 'apply', caller=self.caller)
        self.current = 'true'
        self.groups[1]['Port'] = 30081
        with self.assertRaises(ValueError): module.run(self.config, 'apply', caller=self.caller)
        self.assertEqual(self.writes, [])



    def test_approved_hash_and_helper_hash_are_bound(self):
        path = self.review()
        review = json.loads(path.read_text())
        review['helper_sha256'] = '0'*64
        path.write_text(json.dumps(review))
        with self.assertRaises(ValueError): module.run(self.config, 'apply', caller=self.caller)
        self.config['approved_review_sha256'] = hashlib.sha256(path.read_bytes()).hexdigest()
        with self.assertRaises(ValueError): module.run(self.config, 'apply', caller=self.caller)
        self.assertEqual(self.writes, [])
