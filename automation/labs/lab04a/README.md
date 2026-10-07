# lab04a · Solución del laboratorio

Página: [lab4.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab4.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab04a` de [catalog.yml](../../catalog.yml).

Cuota y JWT se prueban en los namespaces del participante.

Rol canónico: [`roles/lab04a/`](roles/lab04a/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab04a.yml -e lab_id=user7
ansible-playbook playbooks/lab04a.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab04a/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab04a`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
