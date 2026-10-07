# lab00 · Acceso del participante

Página: [lab0.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab0.html).
Contrato: entrada `lab00` de [catalog.yml](../../catalog.yml).

El instructor dispone del wrapper `ansible/playbooks/lab00.yml`: verifica la
entrada en un IdP HTPasswd existente sin escribir por defecto. Alta y rollback
requieren opt-in explícito, guards de API/UID, IdP/Secret concretos y backup
privado. Consulta el [rol Lab00](roles/lab00/README.md) antes de ejecutarlo.

El wrapper no provisiona permisos: el rol común `tenant` prepara namespaces y
RBAC. Tampoco inicia sesión en el navegador, obtiene tokens de UI ni comprueba
la consola. Sigue la página para esos pasos y para cargar variables de sesión.

No hay limpieza masiva de usuarios: rollback sólo retira el hash propio con CAS;
no elimina User/Identity creados por login. La validación real de la sesión está
registrada por separado en [VALIDATION.md](../../VALIDATION.md).
