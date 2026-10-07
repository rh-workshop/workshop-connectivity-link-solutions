# lab04b · Solución del laboratorio

Página: [lab4-api-key.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab4-api-key.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab04b` de [catalog.yml](../../catalog.yml).

La prueba cambia la autenticación de ruta y restaura JWT por defecto.

Rol canónico: [`roles/lab04b/`](roles/lab04b/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab04b.yml -e lab_id=user7
ansible-playbook playbooks/lab04b.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab04b/tasks/validar.yml).
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab04b`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.

Con `lab04b_restaurar_jwt=true` (predeterminado), la restauración se intenta
también si falla una prueba. El fallo original permanece como fallo de Ansible;
restaurar no convierte la validación en PASS. Si falla la comprobación de clave
revocada, se intenta igualmente retirar la AuthPolicy de API key. Un fallo de API
durante limpieza puede impedir completar la restauración: verifica el estado
ante un error y usa la limpieza selectiva antes de continuar.
