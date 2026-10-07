# Escritor Route53 compartido

Módulo interno que crea usuario IAM, política inline y access key. Con
`managed_policy=true` añade una política administrada y su attachment específico
al usuario (`aws_iam_user_policy_attachment`, sin gestionar otros attachments).
Los wrappers seleccionan la zona existente y validan el alcance antes de llamar
al módulo; el proveedor heredado restringe la cuenta AWS autorizada.

Entradas: `identity`, `purpose`, `policy_name`, `zone_id`, `record_patterns`,
`record_types` y `tags`; opcionalmente `managed_policy` (false por defecto) y
`managed_record_patterns` para el alcance ampliado. La política limita la escritura a la zona, los nombres,
los tipos A/AAAA/CNAME/TXT seleccionados y acciones CREATE/UPSERT/DELETE. Conserva
solo las consultas Route53 necesarias. No crea zonas, registros ni balanceadores.

Salidas: `iam_user_name`, `access_key_id` y `secret_access_key` (sensibles),
`policy_json` sin credenciales y `force_destroy` para verificar la retirada segura.
No se ejecuta directamente: usa `dns-credentials` o `ingress-acme` con su backend
privado, guardas de cuenta y pruebas. Nunca reutilices la credencial ACME del
Ingress en namespaces de participantes.

La inline conserva su dirección y permisos originales durante la transición.
Ambas políticas comparten un único generador de condiciones. La administrada usa
un nombre único basado en `identity` y `policy_name`, con path `/rh-workshop/`.
Guardas rechazan JSON compacto mayor que 2048 caracteres (inline) o 6144
(administrada). La clave depende también del attachment al crearse; una clave
existente no cambia. `policy_json` devuelve la política efectiva ampliada y
`inline_policy_json` permite verificar el alcance heredado. Ingress ACME mantiene
la modalidad inline por defecto. La retirada de la inline requiere otra migración.
