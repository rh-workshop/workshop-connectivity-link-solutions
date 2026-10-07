# Rol `lab08` · Servicios externos y un solo token

Publica detrás del Gateway del participante un servicio que corre **fuera del
clúster** (`lab8-servicios-externos.adoc`): Service `ExternalName` + `ServiceEntry`,
HTTPRoute `/inventario` (reescribe a `/v1` y quita `Authorization`), cuota propia
(3/min) y AuthPolicy de ruta que exige el rol de realm `inventario`.
El ServiceEntry se exporta solo a su namespace y a `gateway-<lab_id>`; no comparte
la definición del destino externo con Gateways de otros participantes.

## Encadenar con OpenTofu

La VM externa la crea el módulo `automation/labs/lab08/opentofu`. Su salida `api_public_dns` es el `EXT_HOST` del lab:

```bash
cd automation/ansible
LAB08_TOFU=../labs/lab08/opentofu
ansible-playbook playbooks/lab08.yml -e lab_id=user7 \
  -e lab08_ext_host="$(tofu -chdir="$LAB08_TOFU" output -raw api_public_dns)" \
  -e lab08_ext_port=8080
```

Sin `-e`, el rol toma `EXT_HOST` / `EXT_PORT` del entorno. El grupo de seguridad de
la VM solo admite las IPs de salida del clúster: las pruebas pasan por el Gateway,
nunca directas desde la máquina de control.

## Validación

401 sin token · 200 con `bob` (rol `inventario`) · respuesta del servicio externo con
`path=/v1/items`, `authorization_recibida=false` y `Host` del participante · 403 con
`alice` · **asigna** `inventario` a `alice` en `realm-<N>` con
`community.general.keycloak_user_rolemapping`, pide un token nuevo → 200 · 429 al
agotar la cuota (≤ 3 × 200) · `bank-api` sigue en 200 con el mismo token.

Con `lab08_restaurar_rol: true` (por defecto) se retira el rol a `alice` al final y se
comprueba de nuevo el 403: el realm queda como lo esperan los demás labs. Por eso una
repetición marca siempre `changed=2` (asignar y retirar el rol), por diseño.
