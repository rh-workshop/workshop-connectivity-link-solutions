# lab10 · Solución del laboratorio

Página: [lab10-gobierno.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab10-gobierno.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab10` de [catalog.yml](../../catalog.yml).

Overrides afecta todas las rutas del Gateway del participante.

Rol canónico: [`roles/lab10/`](roles/lab10/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab10.yml -e lab_id=user7
ansible-playbook playbooks/lab10.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab10/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab10`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
