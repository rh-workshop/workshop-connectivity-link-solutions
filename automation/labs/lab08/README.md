# lab08 · Solución del laboratorio

Página: [lab8-servicios-externos.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab8-servicios-externos.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab08` de [catalog.yml](../../catalog.yml).

Requiere lab08_ext_host; OpenTofu crea infraestructura AWS fuera del clúster.

Rol canónico: [`roles/lab08/`](roles/lab08/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab08.yml -e lab_id=user7
ansible-playbook playbooks/lab08.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab08/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab08`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.

Infraestructura externa: [`opentofu/`](opentofu/). Su destrucción es independiente de la limpieza Ansible.

La cuota se comprueba tras 61 segundos sin tráfico de alice al inventario:
con `lab08_cuota=3`, exige exactamente `200 200 200 429` dentro de una ventana
de 60 segundos. Comprueba también el JSON de cada 200 sin repetir peticiones.
Un 429 inicial, tráfico concurrente o una muestra que cruza la ventana hace
fallar la prueba; encontrar algún 429 no basta para demostrar el límite.

Antes de conceder inventario, la validación verifica el UUID de alice y consulta
en Keycloak sus roles directos y efectivos (composites y grupos). Rechaza un rol
inventario preexistente; un HTTP 403 no prueba su ausencia. Solo entonces registra
un marcador con el UUID de la cuenta antes de conceder el rol temporal. Con
`lab08_restaurar_rol=true`, `always` intenta retirarlo incluso si falla una prueba;
el error original sigue siendo un fallo. La limpieza selectiva también retira
esa asignación si existe el marcador propio, sin cambiar otros roles. Sin marcador
no modifica asignaciones preexistentes; si falla la API al retirar el rol, conserva
el marcador para una recuperación posterior. Si alice fue recreada con otro UUID,
la limpieza aborta sin retirar roles de la cuenta nueva. Otros roles y membresías
de grupos no se modifican.

La consulta efectiva usa `role-mappings/realm/composite`: el controlador filtra
con `hasRole`, que incluye grupos. Fuentes oficiales:
[RoleMapperResource](https://github.com/keycloak/keycloak/blob/26.4.7/services/src/main/java/org/keycloak/services/resources/admin/RoleMapperResource.java)
y [UserAdapter](https://github.com/keycloak/keycloak/blob/26.4.7/model/jpa/src/main/java/org/keycloak/models/jpa/UserAdapter.java).
