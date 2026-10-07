# Infraestructura externa del Lab 8

Esta raíz crea la VPC, subred pública, Internet Gateway, rutas, Security Group y
VM RHEL de inventario. No gestiona el clúster, sus NAT Gateways ni los balanceadores
de Services `LoadBalancer`: estos últimos pertenecen a los controladores OpenShift.

`expected_account_id` es obligatorio. Comprueba primero la identidad STS del perfil
autorizado y usa esa misma cuenta en las variables privadas. `cluster_vpc_name`
debe identificar una única VPC del clúster. Sus NAT Gateways disponibles aportan
las IPs públicas permitidas; si no existen, declara los CIDRs de salida explícitos.
Solo se permiten CIDRs IPv4 y se rechaza `0.0.0.0/0`.

## Estado y configuración privados

Conserva el estado, las variables reales y los planes fuera del repositorio:

```bash
umask 077
LAB08_PRIVATE_DIR="$HOME/.local/state/rh-workshop/lab08-user1"
mkdir -p "$LAB08_PRIVATE_DIR"
chmod 700 "$LAB08_PRIVATE_DIR"
cp terraform.tfvars.example "$LAB08_PRIVATE_DIR/inputs.tfvars"
# Ajusta cuenta, VPC y CIDRs autorizados antes de continuar.
tofu init -backend-config="path=$LAB08_PRIVATE_DIR/terraform.tfstate" \
  -backend-config="workspace_dir=$LAB08_PRIVATE_DIR/workspaces"
tofu fmt -check
tofu validate
tofu plan -var-file="$LAB08_PRIVATE_DIR/inputs.tfvars" -out="$LAB08_PRIVATE_DIR/plan"
```

Mantén archivos privados y copias de seguridad con permisos `600`. Las credenciales
se resuelven desde el perfil AWS o el entorno, nunca desde tfvars. El instructor
revisa el plan antes de aplicarlo. `tofu test` ejecuta pruebas con AWS simulado,
sin consultar la cuenta.

Para recursos nuevos, el ejemplo usa `name = "cl-lab08-user1"`. En una migración
conserva el nombre y los valores del estado anterior; no renombres recursos
existentes ni inicialices un estado vacío para adoptarlos. Las direcciones HCL y
el lockfile AWS 5.100.0 permanecen iguales. Si existe un estado local previo,
respalda y migra ese estado privadamente al backend configurado, sin subirlo a Git.

## Salidas y retirada

`api_public_dns` y `api_public_ip` siguen disponibles; usa la primera como EXT_HOST
o `lab08_ext_host` en Ansible. Conserva `api_port` como EXT_PORT.

Retira las rutas/políticas del Lab8 con Ansible antes de destruir su backend.
Revisa `tofu plan -destroy` con el mismo archivo de variables y estado privado;
el instructor ejecuta la retirada aprobada. Esta raíz no borra la VPC del clúster,
sus NAT Gateways ni los balanceadores de los Gateways.
