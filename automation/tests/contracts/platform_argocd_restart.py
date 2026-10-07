"""Reinicio CAS del controlador: contrato nativo sin escrituras Kubernetes."""
import copy
import tempfile
from pathlib import Path
import unittest
import yaml
from common_roles import ROOT, run_tasks

SOURCE = ROOT / 'automation/common/roles/platform_argocd/tasks/controller_restart.yml'
MOCK_FILES = tempfile.TemporaryDirectory()


def fixtures():
    sts = {'metadata': {'name': 'cl-platform-application-controller',
                       'namespace': 'cl-platform-argocd', 'uid': 'sts-uid',
                       'resourceVersion': '43', 'generation': 2,
                       'ownerReferences': [{'uid': 'argo-uid', 'name': 'cl-platform',
                                            'kind': 'ArgoCD', 'controller': True}]},
           'spec': {'replicas': 1, 'updateStrategy': {'type': 'RollingUpdate',
                                                      'rollingUpdate': {'partition': 0}},
                    'selector': {'matchLabels': {'app': 'dedicated-controller'}},
                    'template': {'metadata': {}, 'spec': {'serviceAccountName': 'controller-sa'}}},
           'status': {'currentRevision': 'old'}}
    pod = {'metadata': {'name': 'controller-0', 'uid': 'old-pod',
                        'ownerReferences': [{'uid': 'sts-uid', 'kind': 'StatefulSet', 'controller': True}],
                        'labels': {'controller-revision-hash': 'old'}},
           'spec': {'serviceAccountName': 'controller-sa'},
           'status': {'conditions': [{'type': 'Ready', 'status': 'True'}]}}
    new_sts = copy.deepcopy(sts)
    new_sts['status'] = {'currentRevision': 'new', 'updateRevision': 'new',
                         'observedGeneration': 2, 'readyReplicas': 1,
                         'updatedReplicas': 1, 'currentReplicas': 1}
    new_pod = copy.deepcopy(pod)
    new_pod['metadata']['uid'] = 'new-pod'
    new_pod['metadata']['labels']['controller-revision-hash'] = 'new'
    return {'platform_argocd_restart_apps': {'resources': []},
            'platform_argocd_restart_instance': {'resources': [{'metadata': {'uid': 'argo-uid'}}]},
            'platform_argocd_restart_sts': {'resources': [sts]},
            'platform_argocd_restart_old_pods': {'resources': [pod]},
            'platform_argocd_restart_ready_sts': {'resources': [new_sts]},
            'platform_argocd_restart_ready_pods': {'resources': [new_pod]}}


def mocked(data):
    tasks = copy.deepcopy(yaml.safe_load(SOURCE.read_text()))
    probe = yaml.safe_load((SOURCE.parent / 'controller_restart_probe.yml').read_text())
    for task in probe[0]['block']:
        if 'ansible.builtin.pause' in task:
            task.pop('ansible.builtin.pause')
            task['ansible.builtin.debug'] = {'msg': 'pausa simulada'}
        if 'kubernetes.core.k8s_info' in task:
            task.pop('kubernetes.core.k8s_info')
            register = task.pop('register')
            if register == 'platform_argocd_restart_ready_sts' and 'sts_sequence' in data:
                task['ansible.builtin.set_fact'] = {register: '{{ fixture_sts_sequence[platform_argocd_restart_attempt | int] }}'}
            else:
                task['ansible.builtin.set_fact'] = {register: data[register]}
    probe_path = Path(MOCK_FILES.name) / ('probe-' + str(id(tasks)) + '.yml')
    probe_path.write_text(yaml.safe_dump(probe))
    for task in tasks[0]['block']:
        if 'ansible.builtin.include_tasks' in task:
            name = task['ansible.builtin.include_tasks']
            task['ansible.builtin.include_tasks'] = str(probe_path if name == 'controller_restart_probe.yml' else SOURCE.parent / name)
        if 'kubernetes.core.k8s_info' in task:
            task.pop('kubernetes.core.k8s_info')
            register = task.pop('register')
            task['ansible.builtin.set_fact'] = {register: data[register]}
            if 'until' in task:
                task['retries'] = 1
                task['delay'] = 0
        if 'kubernetes.core.k8s_json_patch' in task:
            patch = task.pop('kubernetes.core.k8s_json_patch')['patch']
            task['ansible.builtin.set_fact'] = {'captured_restart_patch': patch}
    return tasks


class Restart(unittest.TestCase):
    def variables(self, patch=None, explicit=False):
        return {'platform_argocd_controller_plan': {'patch': patch or []},
                'platform_argocd_controller_restart': explicit,
                'wk_platform_argocd': {'namespace': 'cl-platform-argocd', 'name': 'cl-platform',
                                      'service_account': 'controller-sa'},
                'k8s_espera_reintentos': 2, 'k8s_espera_intervalo': 0,
                'platform_argocd_instance': {'resources': [{'metadata': {'uid': 'argo-uid'}}]}}

    def test_transition_and_optin_have_only_template_cas_patch(self):
        expected = [{'op': 'test', 'path': '/metadata/uid', 'value': 'sts-uid'},
                    {'op': 'test', 'path': '/metadata/resourceVersion', 'value': '43'},
                    {'op': 'add', 'path': '/spec/template/metadata/annotations', 'value': {}},
                    {'op': 'add', 'path': '/spec/template/metadata/annotations/connectivity-link.redhat.com~1controller-restart',
                     'value': 'sts-uid:43'}]
        for patch, explicit in [([{'op': 'replace'}], False), ([], True)]:
            tasks = mocked(fixtures()) + [{'ansible.builtin.assert': {
                'that': ['captured_restart_patch == expected_patch']}}]
            result = run_tasks(tasks, dict(self.variables(patch, explicit), expected_patch=expected))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_no_change_no_optin_does_not_restart(self):
        tasks = mocked(fixtures()) + [{'ansible.builtin.assert': {
            'that': ['captured_restart_patch is not defined']}}]
        result = run_tasks(tasks, self.variables())
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_completed_application_is_not_an_active_operation(self):
        for phase in ['Succeeded', 'Failed', 'Error']:
            data = fixtures()
            data['platform_argocd_restart_apps']['resources'] = [
                {'metadata': {'name': 'existing'}, 'operation': None,
                 'status': {'operationState': {'phase': phase}}}]
            result = run_tasks(mocked(data), self.variables(explicit=True))
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_vendor_template_revert_accepts_fresh_ready_process(self):
        data = fixtures()
        # El operador retiró la anotación y volvió a la revisión anterior,
        # pero el proceso renovado conserva UID nuevo, Ready y la misma SA.
        data['platform_argocd_restart_ready_sts']['resources'][0]['status'].update(
            currentRevision='old', updateRevision='old')
        data['platform_argocd_restart_ready_pods']['resources'][0]['metadata']['labels']['controller-revision-hash'] = 'old'
        result = run_tasks(mocked(data), self.variables(explicit=True))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_revision_reverts_between_sts_and_pod_read_retries_both(self):
        data = fixtures()
        first = copy.deepcopy(data['platform_argocd_restart_ready_sts'])
        second = copy.deepcopy(first)
        second['resources'][0]['status'].update(currentRevision='old', updateRevision='old')
        data['sts_sequence'] = [first, second]
        data['platform_argocd_restart_ready_pods']['resources'][0]['metadata']['labels']['controller-revision-hash'] = 'old'
        tasks = mocked(data) + [{'ansible.builtin.assert': {'that': [
            "platform_argocd_restart_ready_sts.resources[0].status.updateRevision == 'old'",
            'platform_argocd_restart_done | bool']}}]
        result = run_tasks(tasks, dict(self.variables(explicit=True), fixture_sts_sequence=data['sts_sequence']))
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_rejects_unsafe_target_and_incomplete_rollout(self):
        for fault in ['application', 'running', 'pending', 'terminating', 'owner', 'partition', 'strategy', 'old-pod', 'not-ready', 'sa', 'revision', 'pod-owner', 'partial', 'transient-revision', 'partial-updated', 'partial-current']:
            data = fixtures()
            sts = data['platform_argocd_restart_sts']['resources'][0]
            pod = data['platform_argocd_restart_ready_pods']['resources'][0]
            if fault == 'application': data['platform_argocd_restart_apps']['resources'] = [{'operation': {'sync': {}}}]
            if fault in ['running', 'pending', 'terminating']:
                data['platform_argocd_restart_apps']['resources'] = [{'status': {'operationState': {'phase': fault.title()}}}]
            if fault == 'owner': sts['metadata']['ownerReferences'][0]['uid'] = 'other-instance'
            if fault == 'partition': sts['spec']['updateStrategy']['rollingUpdate']['partition'] = 1
            if fault == 'strategy': sts['spec']['updateStrategy']['type'] = 'OnDelete'
            if fault == 'old-pod': pod['metadata']['uid'] = 'old-pod'
            if fault == 'not-ready': pod['status']['conditions'][0]['status'] = 'False'
            if fault == 'sa': pod['spec']['serviceAccountName'] = 'other-sa'
            if fault == 'revision': pod['metadata']['labels']['controller-revision-hash'] = 'old'
            if fault == 'pod-owner': pod['metadata']['ownerReferences'][0]['uid'] = 'another-controller'
            if fault == 'partial': data['platform_argocd_restart_ready_pods']['resources'] = []
            if fault == 'transient-revision': data['platform_argocd_restart_ready_sts']['resources'][0]['status']['currentRevision'] = 'old'
            if fault == 'partial-updated': data['platform_argocd_restart_ready_sts']['resources'][0]['status']['updatedReplicas'] = 0
            if fault == 'partial-current': data['platform_argocd_restart_ready_sts']['resources'][0]['status']['currentReplicas'] = 0
            result = run_tasks(mocked(data), self.variables(explicit=True))
            self.assertNotEqual(result.returncode, 0, fault + result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
