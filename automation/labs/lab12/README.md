# lab12 · Solución del laboratorio

Página: [lab12-operacion.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab12-operacion.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab12` de [catalog.yml](../../catalog.yml).

Requiere servicio externo Lab8 y observabilidad Lab5; demos globales son opt-in.

Rol canónico: [`roles/lab12/`](roles/lab12/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab12.yml -e lab_id=user7
ansible-playbook playbooks/lab12.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab12/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab12`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.

Consulta también el [alcance y opciones del rol](roles/lab12/README.md), especialmente las demostraciones globales.
