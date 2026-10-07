# lab11 · Solución del laboratorio

Página: [lab11-seguridad-b2b.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab11-seguridad-b2b.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab11` de [catalog.yml](../../catalog.yml).

Otro LoadBalancer y cambios de red: instructor, capacidad cloud y restauración.

Rol canónico: [`roles/lab11/`](roles/lab11/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab11.yml -e lab_id=user7
ansible-playbook playbooks/lab11.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab11/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab11`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
