# lab06 · Solución del laboratorio

Página: [lab6.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab6.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab06` de [catalog.yml](../../catalog.yml).

Argo CD compartido; el modo local usa Git efímero, el externo requiere permisos.

Rol canónico: [`roles/lab06/`](roles/lab06/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab06.yml -e lab_id=user7
ansible-playbook playbooks/lab06.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab06/tasks/validar.yml).

Para un repositorio privado SSH de GitHub, el instructor registra una **deploy key de sólo lectura**, exclusiva de ese repositorio. Si la organización deshabilita deploy keys, detén la preparación; no sustituyas la clave por un token amplio. Guarda `lab06_git_modo: externo`, `lab06_git_repo_url`, `lab06_repository_credentials_enabled: true` y `lab06_repository_ssh_private_key` en un perfil privado fuera de Git. La clave debe llegar por variables privadas o Vault, nunca por argumentos ni logs.

```bash
ansible-playbook playbooks/lab06.yml -e @/ruta/privada/perfil.yml --tags lab06_repository_credentials
# Sólo tras comprobar destino y permisos; crea el Secret dedicado si no existe:
ansible-playbook playbooks/lab06.yml -e @/ruta/privada/perfil.yml --tags lab06_repository_credentials -e lab06_repository_credentials_verify_only=false
```

Este tag conserva las guardas de `comun`, verifica la instancia y las claves de host existentes, y rechaza Secrets ajenos o diferentes. No instala el operador, no cambia `known_hosts`, no publica commits y no crea una Application. La verificación es el modo predeterminado; el Secret contiene una URL exacta, no credenciales compartidas por prefijo.

El participante puede consultar (`get`) únicamente su Application mediante un Role local en `lab06_argocd_namespace`. El instructor puede preparar sólo este permiso, sin crear la Application ni ejecutar el ejercicio:

```bash
ansible-playbook playbooks/lab06.yml -e @/ruta/privada/perfil.yml --tags lab06_application_view
```

Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab06`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
