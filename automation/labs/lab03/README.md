# lab03 · Solución del laboratorio

Página: [lab3.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab3.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab03` de [catalog.yml](../../catalog.yml).

Namespaces, DNS, TLS y realm requieren preparación del instructor.

Rol canónico: [`roles/lab03/`](roles/lab03/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab03.yml -e lab_id=user7
ansible-playbook playbooks/lab03.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab03/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab03`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
