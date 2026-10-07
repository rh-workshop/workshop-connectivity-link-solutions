# Credencial ACME exclusiva del Ingress

Este wrapper reutiliza `../modules/route53-writer` y crea tres recursos IAM.
Autoriza únicamente TXT para `_acme-challenge.<ingress_domain>` en una zona
pública existente. No permite escribir registros de APIs, A/AAAA/CNAME ni otras
zonas. El nombre autorizado es exacto: no contiene comodines IAM ni DNS.

Lee el dominio del clúster autorizado antes de preparar las variables:

```bash
oc get ingress.config.openshift.io cluster -o jsonpath='{.spec.domain}{"\n"}'
```

`ingress_domain` es obligatorio, en minúsculas y sin `*.` ni protocolo. Define
exactamente una selección `zone_name` o `zone_id`; el dominio debe pertenecer a
esa zona. `expected_account_id` limita el proveedor a la cuenta que el instructor
verificó con STS. El ejemplo solo usa `apps.example.com` y una cuenta ficticia.

## Estado privado y revisión

```bash
umask 077
INGRESS_PRIVATE_DIR="$HOME/.local/state/rh-workshop/ingress-acme-ZEXAMPLE"
mkdir -p "$INGRESS_PRIVATE_DIR"
chmod 700 "$INGRESS_PRIVATE_DIR"
cp terraform.tfvars.example "$INGRESS_PRIVATE_DIR/inputs.tfvars"
# Ajusta la cuenta, zona y dominio obtenido del Ingress autorizado.
tofu init -backend-config="path=$INGRESS_PRIVATE_DIR/terraform.tfstate" \
  -backend-config="workspace_dir=$INGRESS_PRIVATE_DIR/workspaces"
tofu fmt -check
tofu validate
tofu test
tofu plan -var-file="$INGRESS_PRIVATE_DIR/inputs.tfvars" -out="$INGRESS_PRIVATE_DIR/plan"
```

Las pruebas usan AWS simulado. El instructor revisa el plan de tres recursos
antes de aplicar; este componente no ejecuta la instalación del certificado.
Conserva estado, planes, variables y copias privadas con permisos `600`. El estado
contiene la access key: `sensitive` no lo cifra ni impide que `output -json` la
revele. No imprimas la salida ni la guardes en logs o Git.

Entrega `dns_credentials` por Vault al Secret del solver cert-manager, en el
namespace del operador. Usa `zone_id` como `hostedZoneID` del solver Route53.
Mantén esta key separada de DNSPolicy/ACME de participantes y no la copies a sus
namespaces. Un certificado `*.<ingress_domain>` usa el desafío del dominio base;
la credencial no autoriza un patrón wildcard de registros.

## Retirada

Retira primero las referencias del solver y espera a que terminen sus desafíos.
El instructor revisa `tofu plan -destroy` con el mismo estado y variables. Solo se
eliminan usuario, política inline y key propios; no se eliminan la zona existente,
registros, certificados del clúster ni balanceadores gestionados por OpenShift.
