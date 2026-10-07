# lab09 · Solución del laboratorio

Página: [lab9-migracion-3scale.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab9-migracion-3scale.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab09` de [catalog.yml](../../catalog.yml).

Claves de demostración y planes: no usar credenciales reales.

Rol canónico: [`roles/lab09/`](roles/lab09/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Las claves básica y premium comprueban el JSON Party publicado; premium comprueba
también AccountId, Currency, Nickname y longitud de Accounts. Los contratos están
compartidos en `common/roles/comun/defaults/main.yml` y se validan mediante
`probar_http`. La muestra Accounts mantiene seis peticiones: una con contrato
JSON y cinco de la serie. Se añade una petición Party premium independiente;
no se modifica la muestra ni el límite de los planes básico, bronze o silver.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab09.yml -e lab_id=user7
ansible-playbook playbooks/lab09.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab09/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab09`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
