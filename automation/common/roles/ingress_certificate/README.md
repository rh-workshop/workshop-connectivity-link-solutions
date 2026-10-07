# Certificado TLS de Ingress

Usa la plantilla canónica de `automation/platform/kustomize/components/ingress-certificate/`.
El dominio procede de `Ingress.config/cluster`, no de valores de inventario.
No modifica Proxy, certificados de API ni otros campos de IngressController.

Desde `automation/ansible/`, con kubeconfig y configuración privada fuera de Git:

```bash
# Preflight del Certificate ya emitido, antes de cambiar el router.
ansible-playbook playbooks/ingress-certificate.yml -e @/ruta/configuracion-privada.yml \
  -e ingress_certificate_verificar_servicio=false

# Emitir usando el Issuer local Ready (gestor Ansible).
ansible-playbook playbooks/ingress-certificate.yml -e @/ruta/configuracion-privada.yml \
  -e ingress_certificate_mode=issue

# Aplicar únicamente la referencia, conservando el original fuera de Git.
ansible-playbook playbooks/ingress-certificate.yml -e @/ruta/configuracion-privada.yml \
  -e ingress_certificate_mode=apply \
  -e ingress_certificate_backup=/ruta/privada/ingress-original.json

# Verificar referencia activa, operadores y HTTPS servido (modo predeterminado).
ansible-playbook playbooks/ingress-certificate.yml -e @/ruta/configuracion-privada.yml

# Restaurar el campo original; si no existía, eliminar únicamente ese campo.
ansible-playbook playbooks/ingress-certificate.yml -e @/ruta/configuracion-privada.yml \
  -e ingress_certificate_mode=rollback \
  -e ingress_certificate_backup=/ruta/privada/ingress-original.json
```

Con gestor Argo CD, `issue` permanece bloqueado. La transición de la referencia
permite `apply`/`rollback` solo con `ingress_certificate_transicion=true` explícito.
El backup es inmutable: una segunda aplicación con la misma ruta falla antes del
patch; después de un fallo de comprobación usa `verify` o `rollback`.

Antes de aplicar se esperan Issuer/Certificate Ready y se comprueban SAN exactos,
clave correspondiente, expiración superior a siete días y cadena de confianza.
Los SAN incluyen el dominio y su wildcard; `ingress_certificate_incluir_dominio=false`
permite solo el wildcard. Un bundle adicional (`ingress_certificate_trust_bundle`)
se combina con raíces predeterminadas, sin sustituirlas. Claves y PEM viven únicamente
en archivos temporales 0600/directorio 0700, eliminados incluso si falla la validación;
las tareas con el Secret usan `no_log`.

Después del patch se espera generación observada y operadores ingress,
authentication y console disponibles, sin degradación ni progreso. HTTPS de consola
(y Keycloak cuando se detecta) respeta los proxies del entorno y compara el certificado
servido con el Secret validado. `ingress_certificate_verificar_fingerprint=false`
omite esa comparación explícitamente; la confianza y hostname HTTPS siguen activos.
Rollback valida salud/HTTPS usando el bundle configurado, sin exigir el fingerprint nuevo.
