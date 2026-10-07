"""Motor HTTP común: render real Ansible y contrato de respuesta sin red/clúster."""
import ast
import importlib.util
import io
from email.message import Message
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import os
import yaml

ROOT = Path(__file__).resolve().parents[3]
ASSET = ROOT/'automation/common/roles/comun/files/http-echo-server.py'
SPEC = importlib.util.spec_from_file_location('render_backend', ROOT/'automation/scripts/check_render.py')
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)


class SharedBackend(unittest.TestCase):
    def test_real_ansible_lookup_preserves_canonical_program(self):
        fixture = yaml.safe_load((ROOT/'automation/tests/fixtures/render-all.yml').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            plays = []
            for lab in ('lab10', 'lab11'):
                role = ROOT/f'automation/labs/{lab}/roles/{lab}'
                values = yaml.safe_load((role/'defaults/main.yml').read_text())
                values.update(fixture['shared'])
                values.update(fixture['roles'].get(lab, {}))
                values['role_path'] = str(role)
                values['expected_program'] = ASSET.read_text()
                plays.append({'name':lab, 'hosts':'localhost', 'gather_facts':False,
                    'vars':values, 'tasks':[
                        {'ansible.builtin.set_fact':{'backend_resources':
                         "{{ lookup('ansible.builtin.template', '"+str(role/'templates/backend.yaml.j2')+"') | from_yaml_all | list }}"}},
                        {'ansible.builtin.assert':{'that':[
                            'backend_resources[0].data["server.py"] == expected_program'], 'quiet':True}}]})
            playbook = Path(tmp)/'render.yml'
            playbook.write_text(yaml.safe_dump(plays))
            result = subprocess.run(['ansible-playbook', '-i', 'localhost,', '-c', 'local', str(playbook)],
                                    cwd=tmp, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout+result.stderr)

    def test_offline_lookup_allowlist_is_narrow(self):
        role = ROOT/'automation/labs/lab10/roles/lab10'
        self.assertEqual(RENDER.environment(role).globals['lookup']('ansible.builtin.file', str(ASSET)),
                         ASSET.read_text().rstrip('\n'))
        with self.assertRaisesRegex(ValueError, 'no autorizado'):
            RENDER.environment(role).globals['lookup']('ansible.builtin.file', '/etc/hosts')
        with self.assertRaisesRegex(ValueError, 'no autorizado'):
            RENDER.environment(ROOT/'automation/labs/lab12/roles/lab12').globals['lookup']('ansible.builtin.file', str(ASSET))

    def test_response_versions_and_header_filtering(self):
        import json
        # Omitir sólo el arranque del servidor para probar el handler original.
        tree = ast.parse(ASSET.read_text())
        tree.body.pop()
        for version, service in [('v1','gobierno-api'), ('v2','gobierno-api'), ('v1','b2b-api')]:
            scope = {}
            with patch.dict(os.environ, {'API_VERSION':version, 'SERVICE_NAME':service}):
                exec(compile(tree, str(ASSET), 'exec'), scope)
            handler = object.__new__(scope['H'])
            handler.headers = Message()
            for name, value in [('Content-Length','4'), ('Authorization','private-value'),
                                ('X-Forwarded-For','192.0.2.10'), ('X-Client-Common-Name','partner'),
                                ('X-Envoy-Peer-Metadata','hidden'), ('X-Forwarded-Client-Cert','hidden')]:
                handler.headers[name] = value
            handler.rfile = io.BytesIO(b'body')
            handler.wfile = io.BytesIO()
            handler.command, handler.path = 'POST', '/accounts?view=demo'
            codes = []
            handler.send_response = codes.append
            handler.send_header = lambda *_: None
            handler.end_headers = lambda: None
            handler._reply()
            output = json.loads(handler.wfile.getvalue())
            self.assertEqual(codes, [200])
            self.assertEqual((output['service'], output['version'], output['method'], output['body']),
                             (service, version, 'POST', 'body'))
            self.assertTrue(output['authorization_recibida'])
            self.assertNotIn('private-value', handler.wfile.getvalue().decode())
            self.assertEqual(output['x_forwarded_for'], '192.0.2.10')
            self.assertNotIn('X-Envoy-Peer-Metadata', output['cabeceras_x'])
            self.assertNotIn('X-Forwarded-Client-Cert', output['cabeceras_x'])
            self.assertIn('saldo' if version=='v2' else 'balance', output)


if __name__ == '__main__':
    unittest.main()
