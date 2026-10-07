# Selección explícita de subredes para Gateways

Componente **solo de datos**: consulta VPC, instancias del clúster, IGW, subredes y
tablas de rutas existentes. No crea recursos, importa estados, modifica etiquetas
ni cambia rutas. El balanceador pertenece al controlador AWS de OpenShift.

Usa los IDs explícitos cuando las subredes públicas existentes no participan en
el descubrimiento automático. El controlador AWS confirmado para este taller
acepta `service.beta.kubernetes.io/aws-load-balancer-subnets` tanto para CLB como
NLB. La anotación selecciona subredes; no vuelve pública una ruta privada.

## Condiciones comprobadas

- Cuenta restringida por `expected_account_id` en el proveedor.
- VPC explícita y al menos una instancia running con la etiqueta
  `kubernetes.io/cluster/<expected_cluster_id>` igual a `owned` o `shared`.
- Cada ID pertenece a la VPC, sin IDs repetidos y una subred por AZ.
- IGW existente, disponible y asociado a la VPC.
- Tabla asociada con ruta `0.0.0.0/0` hacia ese IGW; una ruta NAT no cumple.
- Al menos `minimum_available_ips` direcciones libres por subred (mínimo 8).

El instructor confirma `expected_cluster_id` contra el `InfrastructureName`
del clúster autorizado. La capacidad y las rutas pueden cambiar: regenera el plan
antes de usar sus salidas.

## Preparación privada

```bash
umask 077
SUBNET_PRIVATE_DIR="$HOME/.local/state/rh-workshop/gateway-subnets"
mkdir -p "$SUBNET_PRIVATE_DIR"
chmod 700 "$SUBNET_PRIVATE_DIR"
cp terraform.tfvars.example "$SUBNET_PRIVATE_DIR/inputs.tfvars"
# Ajusta cuenta, VPC, InfrastructureName e IDs obtenidos de la inspección autorizada.
tofu init -backend-config="path=$SUBNET_PRIVATE_DIR/terraform.tfstate" \
  -backend-config="workspace_dir=$SUBNET_PRIVATE_DIR/workspaces"
tofu fmt -check
tofu validate
tofu test
tofu plan -var-file="$SUBNET_PRIVATE_DIR/inputs.tfvars" -out="$SUBNET_PRIVATE_DIR/plan"
```

Las pruebas usan AWS simulado. El plan real debe tener **cero recursos gestionados**.
El instructor revisa antes de guardar las salidas en el estado. Mantén configuración,
planes y estado fuera de Git, con archivos `600` y directorios `700`.

## Consumo

`aws_load_balancer_subnet_ids` devuelve una lista para el perfil Ansible;
`aws_load_balancer_subnets` devuelve los mismos IDs separados por comas, sin espacios,
para la anotación del Service. La automatización configura esa anotación desde
`Gateway.spec.infrastructure.annotations` y deja que el controlador genere el Service.
`cluster_infrastructure_id` permite contrastar el destinatario de ese perfil.

No añadas tags de propiedad ni declares un NLB/CLB en OpenTofu para este caso.
Retira los Gateways mediante su automatización y comprueba que el controlador libera
los balanceadores. Las subredes, tablas de rutas e IGW existentes permanecen intactos.
