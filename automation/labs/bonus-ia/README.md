# bonus-ia · Solución del laboratorio

Página: [ia-practica.adoc](https://rh-workshop.github.io/workshop-connectivity-link/ia-practica.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `bonus-ia` de [catalog.yml](../../catalog.yml).

Backend simulado; límite de tokens y ventana de cuota, sin proveedor IA real.

Rol canónico: [`roles/bonus_tokens/`](roles/bonus_tokens/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/bonus_tokens.yml -e lab_id=user7
ansible-playbook playbooks/bonus_tokens.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/bonus_tokens/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_bonus_tokens`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
