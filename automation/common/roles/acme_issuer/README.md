# Emisor ACME DNS-01

Fuente canónica del emisor Route53 y de sus credenciales. Por defecto usa
`ClusterIssuer` y Secret en `cert-manager`. Para un emisor namespaced configura
`acme_issuer_kind=Issuer`, `acme_issuer_namespace` y `acme_secret_namespace` con el
mismo namespace existente; el rol no crea ni adopta ese namespace.
No instala cert-manager ni solicita certificados de aplicaciones.

## Configuración privada

Define `acme_route53_hosted_zone_id` (ID `Z…`, sin prefijo), `acme_dns_zone` y
`acme_route53_region`. Aporta `dns_provider_datos` desde vault con
`AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY` y `AWS_REGION` para preparar el Secret.
`acme_email` es opcional y se omite cuando está vacío; no se inventa un contacto.

Usa una clave IAM dedicada y limitada a la hosted zone y registros TXT de
`_acme-challenge`, nunca una clave administrativa. El instructor debe verificar
la política efectiva en AWS: el rol no deduce permisos a partir de una clave.
Route53 necesita `GetChange`, lectura de registros de esa zona y cambios TXT
para los desafíos. Con hostedZoneID explícito no necesita buscar zonas por nombre.
Consulta el [solver oficial Route53](https://cert-manager.io/docs/configuration/acme/dns01/route53/).
No copies estas credenciales al namespace de participantes si su política exige
permisos diferentes para A/CNAME; usa perfiles IAM y Secrets independientes.

## Ejecutar

Desde `automation/ansible/`, con kubeconfig y configuración privada fuera de Git:

```bash
# Solo verifica configuración exacta y Ready del emisor existente.
ansible-playbook playbooks/acme-issuer.yml -e @/ruta/configuracion-privada.yml

# Gestor Ansible: prepara credenciales y reconcilia únicamente objetos propios.
ansible-playbook playbooks/acme-issuer.yml -e @/ruta/configuracion-privada.yml \
  -e acme_issuer_verificar_solo=false

# Gestor Argo CD: bootstrap del Secret antes de sincronizar el emisor público.
ansible-playbook playbooks/acme-issuer.yml -e @/ruta/configuracion-privada.yml \
  -e plataforma_gestor=argocd -e acme_issuer_secret_bootstrap=true \
  -e acme_issuer_esperar_ready=false
```

Después del sync GitOps ejecuta nuevamente la verificación normal. Argo CD nunca
recibe el render de `secret.yaml.j2`. El rol espera CRD Established, Deployment y
endpoints Ready del webhook; rechaza Secrets/emisores sin labels explícitas de
propiedad antes de sobrescribirlos. Todas las operaciones con credenciales usan
`no_log`. Bootstrap de Secret es una excepción explícita al gestor de plataforma.

## Producción y ensayos

El nombre compartido predeterminado es `letsencrypt-dns01`, con servidor
Let’s Encrypt de producción para confianza pública. Para ensayos cambia
`acme_servidor` a `https://acme-staging-v02.api.letsencrypt.org/directory` y usa otro
`acme_issuer_nombre`/`acme_cuenta_secret`; staging no ofrece confianza pública.
Conserva cuentas y certificados para evitar emisiones repetidas y respeta los
[límites de Let’s Encrypt](https://letsencrypt.org/docs/rate-limits/).

Lab 7 usa `playbooks/lab07-acme.yml` para preparar un emisor propio por participante.
El adaptador fija los tres nombres con `lab_id` y activa `acme_issuer_participant_mode`;
el rol exige ese alcance, propiedad `workshop.user` y ausencia de tracking Argo CD.
Esta excepción acotada crea sólo objetos ausentes y verifica los existentes sin
rotarlos. No habilita escrituras sobre el emisor compartido gestionado por GitOps.
