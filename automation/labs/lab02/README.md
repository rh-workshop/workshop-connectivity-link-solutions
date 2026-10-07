# lab02 · Solución del laboratorio

Página: [lab2.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab2.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab02` de [catalog.yml](../../catalog.yml).

Solo lectura; requiere GatewayClass preparada por el instructor.

Rol canónico: [`roles/lab02/`](roles/lab02/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab02.yml -e lab_id=user7
ansible-playbook playbooks/lab02.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab02/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab02`. Este lab no crea recursos; la limpieza es de lectura.
