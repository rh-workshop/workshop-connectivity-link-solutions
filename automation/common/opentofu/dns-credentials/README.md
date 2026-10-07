# Credenciales DNS limitadas por participante

Este componente crea un usuario IAM, una access key y políticas propias
del taller. Conserva la inline heredada y añade una política administrada y su
attachment para el alcance de propiedad de Kuadrant.
Consulta una zona pública existente: **no crea zonas, registros ni
balanceadores**. Los Services `LoadBalancer` de los Gateways siguen siendo propiedad
de los controladores de OpenShift.

La implementación IAM está en `../modules/route53-writer`. Los bloques `moved`
conservan las direcciones anteriores al extraer el módulo. Descarta los planes
guardados antes de esta extracción y genera uno nuevo antes de aplicar.
`../ingress-acme` usa una credencial independiente para el certificado del clúster;
no comparte estas claves de participantes.

Usa un estado y usuario por zona y participante; el nombre IAM incluye el ID de
zona para evitar colisiones entre zonas independientes. Las mismas credenciales limitadas sirven
para su DNSPolicy y el solver ACME Route53. No copies claves administrativas en los
Secrets de participantes; entrega la salida sensible por Ansible Vault. Para ACME,
fija `hostedZoneID` a la salida `zone_id` y configura la referencia a las claves del
Secret mediante la automatización del instructor.

## Alcance

- `expected_account_id` restringe el proveedor a la cuenta autorizada.
- Define `zone_name` o `zone_id`, exactamente uno.
- Autoriza `api-<id>`, `socios-<id>` y `b2b-<id>` bajo `workshop_zone`, y
  `api-<id>` bajo `cloud_zone`, sus descendientes y `_acme-challenge`.
- Configura `workshop_zone` igual que WORKSHOP_ZONE y `cloud_zone` igual que
  `lab07_zona`; ambos deben estar dentro de la zona alojada seleccionada. Si se
  alojan en zonas independientes, usa componentes/estados separados y sus Secrets.
  No asumas que la zona alojada y WORKSHOP_ZONE coinciden. `record_patterns` permite
  restringir aún más los nombres efectivos.
- Solo escribe A, AAAA, CNAME y TXT; CREATE, UPSERT y DELETE deben cumplir todos
  los patrones de nombre. Nunca autoriza cambios NS/SOA ni otra zona.
- Incluye los registros de propiedad de Kuadrant:
  `kuadrant-????????-{a,aaaa,cname}-<host>` (cada `?` es un carácter del hash de
  ocho caracteres). Se derivan de los mismos hosts y descendientes autorizados,
  también cuando `record_patterns` restringe el alcance; no se concede un
  comodín de zona ni permisos para otro participante.
- Las consultas de registros se limitan a la zona; la lista de zonas es global
  porque Route53 no permite limitar esas acciones a una zona. `GetChange` solo
  consulta el estado de cambios; no modifica registros.

Los patrones IAM `*` son comodines de coincidencia, no registros DNS wildcard.
Conserva identificadores de participante exactos; no compartas esta key entre labs
de participantes diferentes. El componente no añade permisos EC2, ELB, IAM ni S3
a la credencial generada.

Kuadrant envía el registro de tráfico y su TXT de propiedad en un mismo lote.
Las condiciones multivalor de Route53 validan el conjunto de nombres y el
conjunto de tipos del lote; IAM no puede correlacionar cada nombre con su tipo.
Por ello, el permiso admite A/AAAA/CNAME/TXT también en esos nombres de propiedad.
Separar un permiso exclusivamente TXT impediría el lote mixto legítimo.
El solver del certificado del clúster conserva su política independiente, TXT
exclusivo y nombre `_acme-challenge` exacto.

Formato verificado en el [generador TXT de Kuadrant](https://github.com/Kuadrant/dns-operator/blob/main/internal/external-dns/registry/name_mapper_kuadrant.go)
y en sus [lotes AWS](https://github.com/Kuadrant/dns-operator/blob/main/internal/external-dns/provider/aws/aws.go).

## Preparación y validación

El instructor verifica primero la identidad STS y la cuenta prevista usando su
perfil autorizado. Mantén estado, planes y variables reales **fuera de Git**:

```bash
umask 077
DNS_PRIVATE_DIR="$HOME/.local/state/rh-workshop/dns-ZEXAMPLE-user1"
mkdir -p "$DNS_PRIVATE_DIR"
chmod 700 "$DNS_PRIVATE_DIR"
cp terraform.tfvars.example "$DNS_PRIVATE_DIR/inputs.tfvars"
# Ajusta cuenta, zona y participante en el archivo privado.
tofu init -backend-config="path=$DNS_PRIVATE_DIR/terraform.tfstate" \
  -backend-config="workspace_dir=$DNS_PRIVATE_DIR/workspaces"
tofu fmt -check
tofu validate
tofu plan -var-file="$DNS_PRIVATE_DIR/inputs.tfvars" -out="$DNS_PRIVATE_DIR/plan"
```

Con un estado nuevo, el plan crea cinco recursos IAM: usuario, key, inline,
política administrada y attachment. Con el estado anterior, la transición crea
solo la política administrada y el attachment: no reemplaza el usuario ni la key
y conserva la inline sin ampliar sus permisos. Descarta planes previos.
La inline evita una ventana sin permisos; su retirada requiere una migración
posterior revisada. Guardas comprueban los límites del JSON compacto antes de
aplicar: inline 2048 y administrada 6144 caracteres. El instructor revisa y aplica
ese plan a la cuenta comprobada. Este ejemplo no ejecuta `apply` automáticamente.
El lockfile conserva AWS 5.100.0 y la identidad `registry.terraform.io/hashicorp/aws`.

Las pruebas de alcance usan un proveedor simulado y no consultan AWS:
`tofu test` (OpenTofu con soporte de mock providers). Incluyen rechazo de otra
zona, otro participante, un comodín de zona y selección ambigua de zona.

`sensitive` oculta la salida habitual, pero la key también existe en el estado;
`output -json` la revela. No la imprimas ni la captures en logs. Mantén estado,
copias de seguridad, planes y exportaciones con permisos `600`, y el directorio
con `700`. Un estado nuevo no adopta recursos existentes: usa siempre el mismo
estado privado; no importes usuarios administrativos.

## Retirada

Retira primero las DNSPolicy y espera la limpieza de sus DNSRecord; termina los
desafíos ACME y elimina las referencias a esta key de los Secrets. Después el
instructor revisa `tofu plan -destroy` usando el mismo archivo privado de variables
y backend. Solo se retiran el attachment, la política administrada, la access key,
la política inline y el usuario creados aquí. La zona y los registros son externos
a este estado. `force_destroy=false`
evita borrar por fuerza un usuario al que se hayan agregado recursos ajenos.

Referencia: [condiciones IAM de Route53](https://docs.aws.amazon.com/Route53/latest/DeveloperGuide/specifying-conditions-route53.html).
