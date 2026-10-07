# Gates nativos de plataforma

Ejecutar `playbooks/platform-gate.yml` desde `automation/ansible` con
`platform_gate_phase=<fase>` y el perfil privado del destino. El wrapper ejecuta
primero `comun`: API efectiva e identidad del clúster antes de las consultas.

`operators` comprueba Subscription/installedCSV, CSV exacto Succeeded y CRDs
Established. Las fases IstioCNI, Istio/GatewayClass, Kuadrant, ClusterIssuer y
Keycloak reutilizan readiness canónica y exigen generación actual cuando la API
la informa. Keycloak admite estados True/true. `keycloak-prerequisites` consulta
Secrets preexistentes sin registrar datos; `rbac` sólo comprueba los ClusterRoles.
`observability` reutiliza la verificación completa del Lab05.
`gateway-defaults` reutiliza el rol canónico en modo consulta: verifica namespace
real de Istio, unicidad y propiedad del ConfigMap y su patch de anotaciones.
Se ejecuta después de Istio y antes de laboratorios cuando el perfil AWS lo activa.

`ingress-certificate` valida el certificado emitido mediante el rol TLS, con
comprobación del certificado servido desactivada antes del cambio. No escribe.
La excepción `ingress-reference` requiere `platform_gate_allow_reference_change:
true`; llama el modo apply del mismo rol, que exige backup privado, valida TLS
criptográfico y comprueba el servicio después de cambiar sólo defaultCertificate.
La transición de propiedad se autoriza mediante los parámetros del rol TLS.

No hay un motor Python adicional de polling ni una confirmación manual que
sustituya la validación TLS. Las pruebas locales usan fixtures Ansible y no
demuestran readiness del clúster real.
