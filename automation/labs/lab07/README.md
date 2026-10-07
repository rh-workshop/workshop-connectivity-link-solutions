# lab07 · Solución del laboratorio

Página: [lab7-cloud.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab7-cloud.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab07` de [catalog.yml](../../catalog.yml).

Solo LoadBalancer: requiere zona pública, DNS y emisor ACME; se omite en route.

Rol canónico: [`roles/lab07/`](roles/lab07/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab07.yml -e lab_id=user7
ansible-playbook playbooks/lab07.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab07/tasks/validar.yml).

El instructor prepara primero ACME por participante con `playbooks/lab07-acme.yml --tags lab07_acme` y el perfil privado (`-e @/ruta/privada/perfil.yml`). El modo predeterminado sólo verifica; añade `-e acme_issuer_verificar_solo=false` únicamente para crear el emisor/Secret ausentes. Este wrapper reutiliza `acme_issuer` y no ejecuta tenant, realm, Gateway ni políticas.

Nombres: `letsencrypt-dns01-<lab_id>` y `acme-route53-credentials-<lab_id>`; la cuenta es `<emisor>-account`. Reutiliza la clave OpenTofu de **ese participante**, después de verificar que su política permite el desafío de `lab07_host`. No amplía IAM ni rota objetos existentes; rechaza otros propietarios o recursos gestionados por Argo CD. Entrega el nombre exacto al alumno como `ACME_ISSUER`.

Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab07`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
