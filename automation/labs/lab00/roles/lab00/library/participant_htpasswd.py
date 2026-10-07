"""Plan CAS de una entrada HTPasswd; nunca modifica OAuth ni registra contraseñas."""
import base64
import json
import os
from pathlib import Path
import re
import subprocess


def decode(value):
    return base64.b64decode(value, validate=True)


def entries(data, username):
    return [line for line in data.splitlines(keepends=True)
            if line.split(b':', 1)[0] == username.encode()]


def validate_name(username):
    if not re.fullmatch(r'[a-z0-9]([-a-z0-9]{0,30}[a-z0-9])?', username):
        raise ValueError('Nombre de participante inválido')


def private_path(value):
    path = Path(value).resolve()
    if not path.parent.is_dir():
        raise ValueError('Directorio privado inexistente')
    result = subprocess.run(['git', '-C', str(path.parent), 'rev-parse', '--show-toplevel'],
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if result.returncode == 0:
        raise ValueError('Backup debe estar fuera de Git')
    return path


def plan(snapshot, username, operation, backup_path='', password=None, binary='htpasswd', idp=''):
    validate_name(username)
    original = decode(snapshot['data']['htpasswd'])
    selected = entries(original, username)
    if operation == 'verify':
        if len(selected) != 1:
            raise ValueError('La entrada del participante no existe o es ambigua')
        return []
    path = private_path(backup_path)
    if operation == 'append':
        if selected:
            raise ValueError('La entrada ya existe; no se adopta ni cambia su contraseña')
        if not password or any(c in password for c in '\r\n\x00'):
            raise ValueError('Contraseña privada obligatoria, sin saltos de línea')
        if path.exists():
            if path.stat().st_mode & 0o077:
                raise ValueError('Backup debe tener permisos privados 0600')
            record = json.loads(path.read_text())
            expected = {'schema_version':1, 'idp':idp, 'username':username,
                        'secret_uid':snapshot['metadata']['uid'],
                        'secret_name':snapshot['metadata']['name'],
                        'secret_namespace':snapshot['metadata']['namespace'],
                        'resource_version':snapshot['metadata']['resourceVersion'],
                        'original_htpasswd':snapshot['data']['htpasswd']}
            if any(record.get(key) != value for key, value in expected.items()):
                raise ValueError('Backup de otro plan o estado cambiado; no reutilizar')
            added = decode(record['added_entry'])
        else:
            result = subprocess.run([binary, '-niB', username], input=(password+'\n').encode(),
                                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=False)
            if result.returncode:
                raise ValueError('No se pudo generar bcrypt')
            added = result.stdout.rstrip(b'\r\n')
            if not re.fullmatch(username.encode()+rb':\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}', added):
                raise ValueError('Salida bcrypt inválida')
            record = {'schema_version':1, 'idp':idp, 'username':username,
                      'secret_uid':snapshot['metadata']['uid'],
                      'secret_name':snapshot['metadata']['name'],
                      'secret_namespace':snapshot['metadata']['namespace'],
                      'resource_version':snapshot['metadata']['resourceVersion'],
                      'original_htpasswd':snapshot['data']['htpasswd'],
                      'added_entry':base64.b64encode(added).decode()}
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, 'w') as stream:
                json.dump(record, stream)
                stream.flush()
                os.fsync(stream.fileno())
        if not re.fullmatch(username.encode()+rb':\$2[aby]\$[0-9]{2}\$[./A-Za-z0-9]{53}', added):
            raise ValueError('Hash registrado inválido')
        updated = original + (b'\n' if original and not original.endswith(b'\n') else b'') + added + b'\n'
    elif operation == 'remove':
        if path.stat().st_mode & 0o077:
            raise ValueError('Backup debe tener permisos privados 0600')
        record = json.loads(path.read_text())
        for key, expected in [('username', username), ('idp', idp),
                              ('secret_uid', snapshot['metadata']['uid']),
                              ('secret_name', snapshot['metadata']['name']),
                              ('secret_namespace', snapshot['metadata']['namespace'])]:
            if record[key] != expected:
                raise ValueError('Backup no pertenece a esta entrada y Secret')
        added = decode(record['added_entry'])
        if len(selected) != 1 or selected[0].rstrip(b'\r\n') != added:
            raise ValueError('Hash distinto o entrada ausente; rollback cancelado')
        # No restaurar la instantánea: conservar entradas concurrentes y sus bytes.
        updated = b''.join(line for line in original.splitlines(keepends=True) if line != selected[0])
    else:
        raise ValueError('Operación no permitida')
    return [{'op':'test', 'path':'/metadata/uid', 'value':snapshot['metadata']['uid']},
            {'op':'test', 'path':'/metadata/resourceVersion', 'value':snapshot['metadata']['resourceVersion']},
            {'op':'test', 'path':'/data/htpasswd', 'value':snapshot['data']['htpasswd']},
            {'op':'replace', 'path':'/data/htpasswd', 'value':base64.b64encode(updated).decode()}]


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(argument_spec={
        # Task-level no_log protege transporte/logs; no redacción del patch en exit_json.
        'snapshot':{'type':'dict', 'required':True},
        'username':{'type':'str', 'required':True},
        'idp':{'type':'str', 'required':True},
        'operation':{'type':'str', 'choices':['verify','append','remove'], 'required':True},
        'backup_path':{'type':'path', 'default':''},
        'password':{'type':'str', 'no_log':True},
        'binary':{'type':'str', 'default':'htpasswd'},
    }, supports_check_mode=True, no_log=True)
    p = module.params
    if module.check_mode and p['operation'] != 'verify':
        module.exit_json(changed=False, skipped=True)
    try:
        patch = plan(p['snapshot'], p['username'], p['operation'], p['backup_path'],
                     p['password'], p['binary'], p['idp'])
        module.exit_json(changed=False, patch=patch)
    except Exception:
        # stderr, contraseña y hashes nunca aparecen en errores de módulo.
        module.fail_json(msg='Entrada rechazada; revisar identidad, operación, backup privado y estado actual. No se modificó el Secret.')


if __name__ == '__main__':
    main()
