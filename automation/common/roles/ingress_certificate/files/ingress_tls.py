#!/usr/bin/env python3
"""Valida TLS localmente; backups externos y patches mínimos. Nunca imprime claves."""
import argparse
import base64
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import ssl
import subprocess
import tempfile
import urllib.request


def openssl(*args, data=None):
    result = subprocess.run(['openssl', *args], input=data, capture_output=True)
    if result.returncode:
        raise ValueError('OpenSSL rechazó la validación TLS: ' + result.stderr.decode(errors='replace').strip())
    return result.stdout


def trust_roots(extra=''):
    paths = ssl.get_default_verify_paths()
    contents = []
    for name in (paths.openssl_cafile, paths.cafile, extra):
        if name and Path(name).is_file():
            content = Path(name).read_bytes()
            if content not in contents:
                contents.append(content)
    if extra and not Path(extra).is_file():
        raise ValueError('El bundle de confianza indicado no existe')
    return b'\n'.join(contents)


def validate_secret(secret, domain, bundle='', min_days=7, require_root=True):
    # El directorio privado se elimina incluso si OpenSSL o la validación fallan.
    with tempfile.TemporaryDirectory(prefix='workshop-ingress-tls-') as folder:
        os.chmod(folder, 0o700)
        def private_file(name, content):
            path = Path(folder) / name
            fd = os.open(path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, 'wb') as stream:
                stream.write(content)
            return str(path)
        chain = base64.b64decode(secret['data']['tls.crt'], validate=True)
        key = private_file('key.pem', base64.b64decode(secret['data']['tls.key'], validate=True))
        certificates = re.findall(rb'-----BEGIN CERTIFICATE-----.*?-----END CERTIFICATE-----', chain, re.S)
        if not certificates:
            raise ValueError('No hay certificado PEM')
        leaf = private_file('leaf.pem', certificates[0])
        san = openssl('x509', '-in', leaf, '-noout', '-ext', 'subjectAltName').decode()
        names = set(re.findall(r'DNS:([^,\s]+)', san))
        expected = {domain, '*.' + domain}
        if '*.' + domain not in names or not names <= expected or (require_root and domain not in names):
            raise ValueError('SAN no corresponde exactamente al dominio Ingress y su wildcard')
        openssl('x509', '-in', leaf, '-checkend', str(min_days * 86400), '-noout')
        cert_key = openssl('x509', '-in', leaf, '-pubkey', '-noout')
        cert_der = openssl('pkey', '-pubin', '-outform', 'DER', data=cert_key)
        key_der = openssl('pkey', '-in', key, '-pubout', '-outform', 'DER')
        if cert_der != key_der:
            raise ValueError('La clave privada no corresponde al certificado')
        args = ['verify', '-purpose', 'sslserver']
        roots = trust_roots(bundle)
        if roots:
            args += ['-CAfile', private_file('trust.pem', roots)]
        if len(certificates) > 1:
            args += ['-untrusted', private_file('intermediates.pem', b'\n'.join(certificates[1:]))]
        openssl(*args, leaf)
        fingerprint = hashlib.sha256(openssl('x509', '-in', leaf, '-outform', 'DER')).hexdigest()
        return dict(domain=domain, sans=sorted(names), sha256=fingerprint,
                    not_after=openssl('x509', '-in', leaf, '-noout', '-enddate').decode().strip().split('=', 1)[1],
                    minimum_remaining_days=min_days, validated=True)


def outside_git(path):
    target = Path(path).expanduser().resolve()
    if any((parent / '.git').exists() for parent in [target.parent, *target.parents]):
        raise ValueError('El backup debe estar fuera de cualquier repositorio Git')
    return target


def save_backup(path, controller, domain, cluster_uid):
    target = outside_git(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    record = dict(domain=domain, cluster_uid=cluster_uid,
                  present='defaultCertificate' in controller.get('spec', {}),
                  defaultCertificate=controller.get('spec', {}).get('defaultCertificate'))
    # No sobrescribir el original durante una segunda aplicación.
    fd = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(record, stream)
    return record


def rollback_patch(path, controller, domain, cluster_uid):
    record = json.loads(outside_git(path).read_text())
    if record['domain'] != domain or record['cluster_uid'] != cluster_uid:
        raise ValueError('El backup no pertenece al dominio/clúster activo')
    if record['present']:
        return [{'op': 'add', 'path': '/spec/defaultCertificate', 'value': record['defaultCertificate']}]
    if 'defaultCertificate' in controller.get('spec', {}):
        return [{'op': 'remove', 'path': '/spec/defaultCertificate'}]
    return []


def verify_served(urls, bundle='', expected_fingerprint=''):
    context = ssl.create_default_context()
    roots = trust_roots(bundle)
    if roots:
        context.load_verify_locations(cadata=roots.decode())
    fingerprints = []
    class RecordingConnection(http.client.HTTPSConnection):
        def connect(self):
            super().connect()
            fingerprints.append(hashlib.sha256(self.sock.getpeercert(binary_form=True)).hexdigest())
    class RecordingHandler(urllib.request.HTTPSHandler):
        def https_open(self, request):
            return self.do_open(RecordingConnection, request, context=context)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler(), RecordingHandler(context=context))
    checked = []
    for url in urls:
        if not url.startswith('https://'):
            raise ValueError('Endpoint TLS debe usar HTTPS')
        before = len(fingerprints)
        with opener.open(url, timeout=60) as response:
            if response.status != 200:
                raise ValueError('Endpoint no devolvió HTTP200')
        if len(fingerprints) == before:
            raise ValueError('No se obtuvo evidencia de certificado servido')
        if expected_fingerprint and any(fp != expected_fingerprint for fp in fingerprints[before:]):
            raise ValueError('El certificado servido no corresponde al Secret validado')
        checked.append(dict(url=url, sha256=fingerprints[before:]))
    return dict(https_checked=checked)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('mode', choices=['validate', 'backup', 'rollback', 'served'])
    parser.add_argument('--domain', default='')
    parser.add_argument('--cluster-uid', default='')
    parser.add_argument('--backup', default='')
    parser.add_argument('--bundle', default='')
    parser.add_argument('--expected-fingerprint', default='')
    parser.add_argument('--min-days', type=int, default=7)
    parser.add_argument('--root-optional', action='store_true')
    args = parser.parse_args()
    import sys
    payload = json.load(sys.stdin)
    if args.mode == 'validate':
        result = validate_secret(payload, args.domain, args.bundle, args.min_days, not args.root_optional)
    elif args.mode == 'backup':
        result = save_backup(args.backup, payload, args.domain, args.cluster_uid)
    elif args.mode == 'rollback':
        result = rollback_patch(args.backup, payload, args.domain, args.cluster_uid)
    else:
        result = verify_served(payload, args.bundle, args.expected_fingerprint)
    print(json.dumps(result))


if __name__ == '__main__':
    main()
