"""TLS/rollback real con certificados de prueba; no usa el clúster ni AWS."""
import base64
import importlib.util
import json
import http.server
import os
import select
import socket
import socketserver
import ssl
import threading
import urllib.error
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock
import yaml
from common_roles import ROOT, ROLES, run_tasks

ROLE = ROLES / 'ingress_certificate'
spec = importlib.util.spec_from_file_location('ingress_tls', ROLE / 'files/ingress_tls.py')
tls = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tls)


class IngressCertificate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.folder = tempfile.TemporaryDirectory()
        cls.directory = Path(cls.folder.name)
        cls.domain = 'apps.example.invalid'
        def command(*args):
            subprocess.run(['openssl', *args], cwd=cls.directory, check=True, capture_output=True)
        cls.command = staticmethod(command)
        command('req', '-x509', '-newkey', 'rsa:2048', '-nodes', '-keyout', 'ca.key', '-out', 'ca.pem',
                '-days', '30', '-subj', '/CN=Workshop Test CA',
                '-addext', 'basicConstraints=critical,CA:TRUE', '-addext', 'keyUsage=critical,keyCertSign,cRLSign',
                '-addext', 'subjectKeyIdentifier=hash')
        cls.good = cls.certificate('good', cls.domain, 15)
        cls.bad_domain = cls.certificate('bad-domain', 'apps.other.invalid', 15)
        cls.expiring = cls.certificate('expiring', cls.domain, 1)

    @classmethod
    def tearDownClass(cls):
        cls.folder.cleanup()

    @classmethod
    def certificate(cls, name, domain, days):
        cls.command('req', '-new', '-newkey', 'rsa:2048', '-nodes', '-keyout', name+'.key',
                    '-out', name+'.csr', '-subj', '/CN='+domain)
        (cls.directory/(name+'.ext')).write_text('subjectAltName=DNS:'+domain+',DNS:*.'+domain+'\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nbasicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\n')
        cls.command('x509', '-req', '-in', name+'.csr', '-CA', 'ca.pem', '-CAkey', 'ca.key', '-CAcreateserial',
                    '-out', name+'.pem', '-days', str(days), '-extfile', name+'.ext')
        return {'data': {'tls.crt': base64.b64encode((cls.directory/(name+'.pem')).read_bytes()).decode(),
                         'tls.key': base64.b64encode((cls.directory/(name+'.key')).read_bytes()).decode()}}

    def test_real_tls_san_key_expiry_and_chain(self):
        ca = str(self.directory/'ca.pem')
        result = tls.validate_secret(self.good, self.domain, ca)
        self.assertTrue(result['validated'])
        self.assertEqual(set(result['sans']), {self.domain, '*.'+self.domain})
        self.assertEqual(len(result['sha256']), 64)
        mismatch = json.loads(json.dumps(self.good))
        mismatch['data']['tls.key'] = self.bad_domain['data']['tls.key']
        for secret, domain, bundle in [(self.bad_domain, self.domain, ca), (self.good, 'wrong.invalid', ca),
                                       (self.expiring, self.domain, ca), (mismatch, self.domain, ca),
                                       (self.good, self.domain, '')]:
            with self.subTest(domain=domain, bundle=bundle):
                with self.assertRaises((ValueError, KeyError)):
                    tls.validate_secret(secret, domain, bundle)

    def test_private_files_always_removed(self):
        original = tempfile.TemporaryDirectory
        created = []
        def recording(*args, **kwargs):
            obj = original(*args, **kwargs)
            created.append(Path(obj.name))
            return obj
        with mock.patch.object(tls.tempfile, 'TemporaryDirectory', side_effect=recording):
            with self.assertRaises(ValueError):
                tls.validate_secret(self.bad_domain, self.domain, str(self.directory/'ca.pem'))
        self.assertTrue(created)
        self.assertTrue(all(not folder.exists() for folder in created))

    def test_backup_and_rollback_present_and_absent(self):
        for controller, expected in [({'spec': {}}, [{'op': 'remove', 'path': '/spec/defaultCertificate'}]),
                ({'spec': {'defaultCertificate': {'name': 'original'}}},
                 [{'op': 'add', 'path': '/spec/defaultCertificate', 'value': {'name': 'original'}}])]:
            with tempfile.TemporaryDirectory() as folder:
                path = str(Path(folder)/'backup.json')
                tls.save_backup(path, controller, self.domain, 'uid-fixture')
                self.assertEqual(Path(path).stat().st_mode & 0o777, 0o600)
                self.assertEqual(tls.rollback_patch(path, {'spec': {'defaultCertificate': {'name': 'new'}}},
                                                   self.domain, 'uid-fixture'), expected)
                with self.assertRaises(FileExistsError):
                    tls.save_backup(path, {'spec': {}}, self.domain, 'uid-fixture')
                with self.assertRaises(ValueError):
                    tls.rollback_patch(path, {'spec': {}}, 'wrong.invalid', 'uid-fixture')
                with self.assertRaises(ValueError):
                    tls.rollback_patch(path, {'spec': {}}, self.domain, 'wrong-uid')
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, '.git').mkdir()
            with self.assertRaises(ValueError):
                tls.save_backup(str(Path(folder)/'backup.json'), {'spec': {}}, self.domain, 'uid')

    def test_https_served_fingerprint_and_proxy_connect(self):
        served = self.certificate('served', 'localhost', 15)
        ca = str(self.directory/'ca.pem')
        fingerprint = tls.validate_secret(served, 'localhost', ca)['sha256']
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'workshop fixture')
            def log_message(self, *args):
                pass
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(self.directory/'served.pem'), str(self.directory/'served.key'))
        server.socket = context.wrap_socket(server.socket, server_side=True)
        connections = []
        class Proxy(socketserver.StreamRequestHandler):
            def handle(self):
                first = self.rfile.readline().decode().strip()
                connections.append(first)
                while self.rfile.readline().strip():
                    pass
                with socket.create_connection(('127.0.0.1', server.server_port)) as peer:
                    self.wfile.write(b'HTTP/1.1 200 Connection Established\r\n\r\n')
                    self.wfile.flush()
                    while True:
                        readable, _, _ = select.select([self.connection, peer], [], [], 3)
                        if not readable:
                            return
                        for source in readable:
                            data = source.recv(65536)
                            if not data:
                                return
                            (peer if source is self.connection else self.connection).sendall(data)
        proxy = socketserver.ThreadingTCPServer(('127.0.0.1', 0), Proxy)
        proxy.daemon_threads = True
        threads = [threading.Thread(target=instance.serve_forever, daemon=True) for instance in (server, proxy)]
        for thread in threads:
            thread.start()
        url = f'https://localhost:{server.server_port}/'
        try:
            with mock.patch.dict(os.environ, {}, clear=True):
                result = tls.verify_served([url], ca, fingerprint)
                self.assertEqual(result['https_checked'][0]['sha256'], [fingerprint])
                with self.assertRaisesRegex(ValueError, 'Secret validado'):
                    tls.verify_served([url], ca, '0'*64)
                with self.assertRaises(urllib.error.URLError):
                    tls.verify_served([url])
            with mock.patch.dict(os.environ, {'HTTPS_PROXY': f'http://127.0.0.1:{proxy.server_address[1]}', 'NO_PROXY': ''}, clear=True):
                result = tls.verify_served([url], ca, fingerprint)
                self.assertEqual(result['https_checked'][0]['sha256'], [fingerprint])
            self.assertTrue(any(line.startswith('CONNECT localhost:') for line in connections))
        finally:
            for instance in (server, proxy):
                instance.shutdown()
                instance.server_close()
            for thread in threads:
                thread.join(timeout=5)

    def test_modes_ownership_and_minimal_patch(self):
        main = yaml.safe_load((ROLE/'tasks/main.yml').read_text())
        mode_guard = next(task for task in main if task.get('ansible.builtin.include_role', {}).get('tasks_from') == 'validar_gestor')
        for mode, transition, success in [('verify', False, True), ('issue', False, False),
                ('issue', True, False), ('apply', False, False), ('apply', True, True), ('rollback', True, True)]:
            result = run_tasks([{'ansible.builtin.import_tasks': str(ROLES/'comun/tasks/validar_gestor.yml'),
                                 'vars': mode_guard['vars']}], dict(plataforma_gestor='argocd',
                                           ingress_certificate_mode=mode, ingress_certificate_transicion=transition))
            self.assertEqual(result.returncode == 0, success, result.stdout+result.stderr)
        apply = yaml.safe_load((ROLE/'tasks/apply.yml').read_text())
        for evidence in [{'validated': False, 'domain': self.domain, 'sha256': 'a'*64},
                         {'validated': True, 'domain': 'wrong.invalid', 'sha256': 'a'*64},
                         {'validated': True, 'domain': self.domain, 'sha256': ''}]:
            result = run_tasks([apply[0], {'ansible.builtin.debug': {'msg': 'PATCH_WOULD_EXECUTE'}}],
                               dict(ingress_tls_evidence=evidence, ingress_domain=self.domain))
            self.assertNotEqual(result.returncode, 0, result.stdout)
            self.assertNotIn('PATCH_WOULD_EXECUTE', result.stdout)
        self.assertEqual(apply[-1]['kubernetes.core.k8s']['definition'],
                         {'spec': {'defaultCertificate': {'name': '{{ ingress_certificate_secret }}'}}})
        backup = next(task for task in apply if 'ansible.builtin.command' in task)
        self.assertEqual(backup['ansible.builtin.command']['argv'][2], 'backup')
        self.assertTrue(backup['no_log'])
        self.assertEqual(apply[1]['kubernetes.core.k8s_info']['kind'], 'IngressController')
        validation = yaml.safe_load((ROLE/'tasks/validar_tls.yml').read_text())
        self.assertTrue(next(task for task in validation if 'kubernetes.core.k8s_info' in task)['no_log'])
        self.assertTrue(next(task for task in validation if 'ansible.builtin.command' in task)['no_log'])
        wrapper = yaml.safe_load((ROOT/'automation/ansible/playbooks/ingress-certificate.yml').read_text())
        self.assertEqual([role['role'] for role in wrapper[0]['roles']], ['comun', 'ingress_certificate'])


if __name__ == '__main__':
    unittest.main()
