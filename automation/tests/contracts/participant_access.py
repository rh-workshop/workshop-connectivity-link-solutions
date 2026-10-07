"""CAS y rollback de HTPasswd sin tocar clúster ni publicar credenciales."""
import base64
import copy
import importlib.util
from pathlib import Path
import subprocess
import os
import shlex
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml
from jinja2 import Environment

ROOT = Path(__file__).resolve().parents[3]
ROLE = ROOT/'automation/labs/lab00/roles/lab00'
SPEC = importlib.util.spec_from_file_location('participant_entry', ROLE/'library/participant_htpasswd.py')
P = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(P)


def snapshot(data=b'admin:$2y$old-admin-hash\nother:{SHA}old-hash\n'):
    return {'metadata':{'uid':'secret-uid', 'resourceVersion':'7', 'namespace':'openshift-config', 'name':'htpasswd'},
            'data':{'htpasswd':base64.b64encode(data).decode(), 'unrelated':'unchanged'}}


def apply_patch(resource, operations):
    obj = copy.deepcopy(resource)
    for operation in operations:
        parent, key = operation['path'].strip('/').split('/')
        if operation['op'] == 'test':
            if obj[parent][key] != operation['value']:
                raise ValueError('CAS conflict')
        else:
            obj[parent][key] = operation['value']
    return obj

def shebang_python(cli, lookup=shutil.which):
    # Resolver el CLI; conservar ruta del Python venv (resolver su symlink rompe venv).
    line = Path(cli).resolve().read_text().splitlines()[0]
    if not line.startswith('#!'):
        raise RuntimeError('El CLI Ansible no declara intérprete; configura RH_WORKSHOP_ANSIBLE_PYTHON')
    parts = shlex.split(line[2:].strip())
    if Path(parts[0]).name == 'env':
        parts = parts[1:]
        if parts and parts[0] == '-S':
            parts = parts[1:]
        if not parts or parts[0].startswith('-') or '=' in parts[0]:
            raise RuntimeError('Shebang env no admitido; configura RH_WORKSHOP_ANSIBLE_PYTHON')
        binary = lookup(parts[0])
        if not binary:
            raise RuntimeError('Python del shebang no disponible')
        return [binary]+parts[1:]
    return parts


def has_ansible(command):
    try:
        return subprocess.run(command+['-c', 'from ansible.module_utils.basic import AnsibleModule'],
                              capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def ansible_python():
    explicit = os.environ.get('RH_WORKSHOP_ANSIBLE_PYTHON')
    if explicit:
        command = [explicit]
        if not has_ansible(command):
            raise RuntimeError('RH_WORKSHOP_ANSIBLE_PYTHON no puede importar AnsibleModule')
        return command
    current = [sys.executable]
    if has_ansible(current):
        return current
    cli = shutil.which('ansible-playbook') or shutil.which('ansible')
    if cli:
        command = shebang_python(cli)
        if has_ansible(command):
            return command
    raise RuntimeError('Regresión AnsibleModule no disponible: instala Ansible o configura RH_WORKSHOP_ANSIBLE_PYTHON; no se omite esta prueba')


def task_list():
    tasks = yaml.safe_load((ROLE/'tasks/main.yml').read_text())
    return tasks + [child for task in tasks for child in task.get('block', [])]


class ParticipantAccess(unittest.TestCase):
    def make_plan(self, source, path):
        return P.plan(source, 'user90', 'append', str(path), 'private-test-password', idp='existing-idp')

    def test_append_preserves_every_original_byte_and_uses_stdin(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = snapshot()
            plan = self.make_plan(original, Path(tmp)/'backup.json')
            updated = apply_patch(original, plan)
            self.assertTrue(P.decode(updated['data']['htpasswd']).startswith(P.decode(original['data']['htpasswd'])))
            self.assertEqual(updated['data']['unrelated'], 'unchanged')
            self.assertEqual([op['path'] for op in plan], ['/metadata/uid','/metadata/resourceVersion','/data/htpasswd','/data/htpasswd'])
            self.assertEqual((Path(tmp)/'backup.json').stat().st_mode & 0o777, 0o600)
            self.assertNotIn('private-test-password', (Path(tmp)/'backup.json').read_text())
            self.assertNotIn('private-test-password', str(plan))
            P.plan(updated, 'user90', 'verify')
            with self.assertRaises(ValueError):
                self.make_plan(updated, Path(tmp)/'other.json')

    def test_cas_conflict_and_rollback_preserve_concurrent_user(self):
        with tempfile.TemporaryDirectory() as tmp:
            original = snapshot()
            backup = Path(tmp)/'backup.json'
            plan = self.make_plan(original, backup)
            for section, key, value in [('metadata','uid','foreign-uid'),('metadata','resourceVersion','8'),
                                        ('data','htpasswd',base64.b64encode(b'concurrent:hash\n').decode())]:
                stale = copy.deepcopy(original)
                stale[section][key] = value
                with self.assertRaisesRegex(ValueError, 'CAS conflict'):
                    apply_patch(stale, plan)
            current = apply_patch(original, plan)
            data = P.decode(current['data']['htpasswd']) + b'concurrent:{SHA}keep-me\n'
            current['data']['htpasswd'] = base64.b64encode(data).decode()
            current['metadata']['resourceVersion'] = '9'
            rollback = P.plan(current, 'user90', 'remove', str(backup), idp='existing-idp')
            restored = apply_patch(current, rollback)
            self.assertEqual(P.decode(restored['data']['htpasswd']), P.decode(original['data']['htpasswd'])+b'concurrent:{SHA}keep-me\n')
            current['data']['htpasswd'] = base64.b64encode(data.replace(b'user90:', b'user90:changed')).decode()
            with self.assertRaises(ValueError):
                P.plan(current, 'user90', 'remove', str(backup), idp='existing-idp')

    def test_invalid_name_foreign_backup_and_no_password_argv(self):
        with tempfile.TemporaryDirectory() as tmp:
            for name in ('admin:name', 'User90', '../user', 'a'*33):
                with self.assertRaises(ValueError):
                    P.plan(snapshot(), name, 'append', str(Path(tmp)/'invalid'), 'secret')
            fake = subprocess.CompletedProcess([], 0, stdout=b'user90:$2y$05$'+b'a'*53+b'\n', stderr=b'')
            original_run = subprocess.run
            def run(args, **kwargs):
                if args[0] == 'htpasswd':
                    self.assertEqual(args, ['htpasswd','-niB','user90'])
                    self.assertEqual(kwargs['input'], b'private-test-password\n')
                    return fake
                return original_run(args, **kwargs)
            backup = Path(tmp)/'backup.json'
            with patch.object(P.subprocess, 'run', side_effect=run):
                plan = self.make_plan(snapshot(), backup)
            altered = apply_patch(snapshot(), plan)
            altered['metadata']['uid'] = 'foreign'
            with self.assertRaises(ValueError):
                P.plan(altered, 'user90', 'remove', str(backup), idp='existing-idp')
            with self.assertRaises(ValueError):
                P.private_path(ROOT/'private-backup.json')

    def test_immutable_backup_retry_and_real_module_cas_values(self):
        import json
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'backup.json'
            original = snapshot()
            planned = self.make_plan(original, path)
            backup_bytes = path.read_bytes()
            self.assertEqual(self.make_plan(original, path), planned)
            self.assertEqual(path.read_bytes(), backup_bytes)
            stale = copy.deepcopy(original)
            stale['metadata']['resourceVersion'] = 'changed'
            with self.assertRaises(ValueError):
                self.make_plan(stale, path)
            # AnsibleModule real: argument-level no_log no debe destruir valores del CAS.
            python = ansible_python()
            args = {'ANSIBLE_MODULE_ARGS':{'_ansible_no_log':True, 'snapshot':original,
                    'username':'user90','idp':'existing-idp','operation':'append',
                    'backup_path':str(path),'password':'private-test-password','binary':'htpasswd'}}
            result = subprocess.run(python+[str(ROLE/'library/participant_htpasswd.py')],
                                    input=json.dumps(args),capture_output=True,text=True)
            self.assertEqual(result.returncode,0,'Module failed without exposing private output')
            output = json.loads(result.stdout)
            self.assertEqual(output['patch'], planned)
            self.assertNotIn('VALUE_SPECIFIED_IN_NO_LOG_PARAMETER', str(output['patch']))
            self.assertNotIn('private-test-password', result.stdout+result.stderr)

    def test_portable_ansible_interpreter_resolution(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp)/'ansible-playbook'
            link = Path(tmp)/'cli-link'
            link.symlink_to(script)
            for shebang, expected in [('#!/opt/venvs/ansible/bin/python', ['/opt/venvs/ansible/bin/python']),
                                      ('#!/usr/bin/env python3', ['/usr/local/bin/python3']),
                                      ('#!/usr/bin/env -S python3 -I', ['/usr/local/bin/python3','-I'])]:
                script.write_text(shebang+'\n')
                self.assertEqual(shebang_python(link,lookup=lambda _: '/usr/local/bin/python3'),expected)
        with patch.dict(os.environ,{'RH_WORKSHOP_ANSIBLE_PYTHON':'/private/venv/bin/python'}), patch(__name__+'.has_ansible',return_value=True):
            self.assertEqual(ansible_python(),['/private/venv/bin/python'])
        with patch.dict(os.environ,{'RH_WORKSHOP_ANSIBLE_PYTHON':'/invalid/python'}), patch(__name__+'.has_ansible',return_value=False):
            with self.assertRaisesRegex(RuntimeError,'no puede importar'):
                ansible_python()
        with patch.dict(os.environ,{},clear=True), patch(__name__+'.has_ansible',return_value=False), patch.object(shutil,'which',return_value=None):
            with self.assertRaisesRegex(RuntimeError,'no se omite'):
                ansible_python()

    def test_canonical_binding_and_readonly_rules_only(self):
        tasks = task_list()
        env = Environment()
        binding_checks = next(t for t in tasks if 'vínculo canónico' in t['name'])['ansible.builtin.assert']['that']
        binding = {'metadata':{'name':'user90-gatewayclass-view', 'labels':{'workshop.user':'user90','workshop.module':'connectivity-link'}},
                   'roleRef':{'apiGroup':'rbac.authorization.k8s.io','kind':'ClusterRole','name':'workshop-gatewayclass-view'},
                   'subjects':[{'kind':'User','name':'user90','apiGroup':'rbac.authorization.k8s.io'}]}
        def accepted(value):
            return all(env.compile_expression(e)(item=value,lab_id='user90') for e in binding_checks)
        self.assertTrue(accepted(binding))
        for field, value in [('roleRef', {'kind':'ClusterRole','name':'cluster-admin'}),
                             ('subjects',[{'kind':'User','name':'foreign'}]),
                             ('metadata',{'name':'user90-gatewayclass-view','labels':{'workshop.user':'foreign','workshop.module':'connectivity-link'}})]:
            changed = copy.deepcopy(binding)
            changed[field] = value
            self.assertFalse(accepted(changed))
        # Obtener las reglas canónicas de la fuente única, no un segundo manifiesto golden.
        canonical = list(yaml.safe_load_all((ROOT/'automation/common/roles/plataforma/templates/workshop-rbac.yaml.j2').read_text().split('---')[0]))[0]['rules']
        rule_checks = next(t for t in tasks if 'tres reglas canónicas' in t['name'])['ansible.builtin.assert']['that']
        verb_checks = next(t for t in tasks if 'Verificar verbos exactos' in t['name'])['ansible.builtin.assert']['that']
        def rules_allowed(rules):
            if not all(env.compile_expression(e)(participant_access_gateway_role={'resources':[{'rules':rules}]}) for e in rule_checks):
                return False
            return all(env.compile_expression(e)(item=rule) for rule in rules for e in verb_checks)
        self.assertTrue(rules_allowed(canonical))
        self.assertTrue(rules_allowed(list(reversed(canonical))))
        for mutate in [lambda r:r[0]['verbs'].append('create'), lambda r:r[1].update(resources=['*']),
                       lambda r:r[2].update(nonResourceURLs=['*']), lambda r:r.append({'apiGroups':['*'],'resources':['*'],'verbs':['*']})]:
            changed = copy.deepcopy(canonical)
            mutate(changed)
            self.assertFalse(rules_allowed(changed))

    def test_group_deny_and_remove_exemption_and_explicit_secret(self):
        tasks = task_list()
        env = Environment()
        env.filters['difference'] = lambda a,b: list(set(a)-set(b))
        group_guard = next(t for t in tasks if 'membresías adicionales' in t['name'])['ansible.builtin.assert']['that']
        # Un grupo custom-admin se rechaza sin depender del nombre de su ClusterRole.
        values = {'participant_access_group_names':['system:authenticated','custom-admin'],
                  'participant_access_users':{'resources':[]}}
        self.assertFalse(all(env.compile_expression(e)(**values) for e in group_guard))
        block = next(t for t in tasks if 'Revisar privilegios sólo' in t['name'])
        self.assertFalse(env.compile_expression(block['when'])(participant_access_operation='remove'))
        self.assertTrue(env.compile_expression(block['when'])(participant_access_operation='append'))
        checks = next(t for t in tasks if 'mapping no admitido' in t['name'])['ansible.builtin.assert']['that']
        idp = {'type':'HTPasswd','mappingMethod':'claim','htpasswd':{'fileData':{'name':'expected-secret'}}}
        self.assertTrue(all(env.compile_expression(e)(participant_access_idps=[idp],participant_idp_secret_name='expected-secret') for e in checks))
        self.assertFalse(all(env.compile_expression(e)(participant_access_idps=[idp],participant_idp_secret_name='other-secret') for e in checks))

    def test_privilege_and_existing_identity_guards(self):
        tasks = task_list()
        inherited = next(t for t in tasks if 'heredado de un grupo' in t['name'])['ansible.builtin.assert']['that']
        env = Environment()
        binding = {'subjects':[{'kind':'Group','name':'admins'}]}
        self.assertFalse(env.compile_expression(inherited)(item=binding,participant_access_group_names=['admins']))
        guard = next(t for t in tasks if 'No adoptar User' in t['name'])['ansible.builtin.assert']['that']
        vars = {'participant_access_users':{'resources':[{'metadata':{'name':'user90'}}]},
                'participant_access_identities':{'resources':[]}}
        self.assertFalse(all(env.compile_expression(e)(**vars) for e in guard))
        secret_tasks = [t for t in tasks if any(k in t for k in ('participant_htpasswd','kubernetes.core.k8s_json_patch'))]
        self.assertTrue(all(t.get('no_log') for t in secret_tasks))
        self.assertFalse(any('kubernetes.core.k8s' in t for t in tasks))  # Sin apply/OAuth overwrite.


if __name__ == '__main__':
    unittest.main()
