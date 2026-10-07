# lab01 · Solución del laboratorio

Página: [lab1.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab1.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab01` de [catalog.yml](../../catalog.yml).

Solo lectura; requiere plataforma preparada por el instructor.

Rol canónico: [`roles/lab01/`](roles/lab01/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab01.yml -e lab_id=user7
ansible-playbook playbooks/lab01.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab01/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab01`. Este lab no crea recursos; la limpieza es de lectura.
