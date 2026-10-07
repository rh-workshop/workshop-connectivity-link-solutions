# Lab00: acceso del participante

Este rol añade **sólo** `lab_id` a un IdP HTPasswd existente elegido por el
instructor. No crea IdPs, modifica OAuth, asigna permisos ni elimina User/Identity.
Los namespaces y permisos del participante siguen en el rol `tenant`.
El módulo y sus tareas usan `no_log`: nunca invocarlo para imprimir su patch,
que contiene datos privados del Secret. El argumento snapshot no se redacta
antes de retornar el CAS; la protección es a nivel de módulo/tarea.

El wrapper es `automation/ansible/playbooks/lab00.yml`. El modo por defecto
`participant_access_verificar_solo: true` sólo verifica el IdP y la presencia de
la entrada. Son obligatorios `participant_idp_name`, `participant_idp_secret_name`,
`openshift_api_esperada` y
`openshift_cluster_uid_esperado`; no existe selección automática ni fallback.
El nombre del Secret debe coincidir exactamente con el configurado en el IdP.
La entrada sólo se admite con mappingMethod `claim` o `add`.

Para alta explícita, usa `participant_access_verificar_solo: false`, operación
`append`, `participant_password` y `participant_access_backup_path`. Entrega esos
valores desde un perfil privado/Vault fuera de Git, sin contraseñas en argumentos
CLI, stdout o historial. El ejecutable `htpasswd` genera bcrypt leyendo stdin;
`participant_access_htpasswd_binary` permite fijar su ruta local.

El backup JSON se crea 0600, fuera de cualquier checkout y sin sobrescribirlo.
Un reintento del mismo plan puede reutilizarlo únicamente si IdP, usuario,
UID, resourceVersion y contenido previo siguen idénticos; conserva el hash
registrado y la contraseña de la operación original, sin generar otra ni
sobrescribir el archivo. Cualquier cambio exige releer y preparar otro plan.
Contiene los bytes HTPasswd previos y el hash añadido, nunca la contraseña.
La escritura sólo reemplaza `data.htpasswd` después de probar UID, resourceVersion
y bytes previos mediante JSON Patch. Un conflicto aborta: releer estado y preparar
una nueva operación/backup; nunca restaurar el Secret completo ni reusar un plan
obsoleto. Todos los hashes y entradas previas permanecen intactos.

Rollback explícito: operación `remove` con el backup correspondiente y modo de
escritura habilitado. Sólo retira la línea si el hash actual coincide con el
registrado; conserva entradas concurrentes y repite CAS. No elimina User/Identity
creados por login: su borrado requeriría seguimiento de UID y una operación
separada aún no implementada. Los guards de privilegios se aplican al alta;
el rollback del hash propio permanece disponible si el RBAC cambió después.
El alta sólo acepta el binding canónico de lectura de GatewayClass con sus tres
reglas exactas; rechaza otros vínculos globales y grupos adicionales hasta una
revisión de sus permisos efectivos.

El alta se hace sobre el IdP existente con este wrapper; no se crea un IdP
nuevo. Login real y navegación de consola siguen
manuales; las pruebas offline no demuestran autenticación ante el clúster.
