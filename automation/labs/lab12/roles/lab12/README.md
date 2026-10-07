# Rol `lab12` · Operación y resiliencia

Automatiza el **estado final por participante** de `lab12-operacion.adoc`:

- `PrometheusRule` `api-429-<lab_id>` (alerta `CuotaAgotada`) en `gateway-<lab_id>`
  — en el namespace del Gateway, no en el de la app: UWM inyecta el namespace de
  la regla y las métricas de Istio llevan el del `PodMonitor`.
- `RoleBinding` `<lab_id>-monitoring-rules` (`monitoring-rules-edit`), el mismo que
  crea el rol `tenant`.
- Validación: `SubjectAccessReview` (≡ `oc auth can-i create prometheusrules`),
  regla cargada en Thanos Ruler, las tres consultas PromQL del paso 8 con series, y
  (con `lab12_esperar_alerta: true`) carga que supera la cuota hasta que la alerta
  pasa a `firing` (~3-4 min).

**La carga va por defecto a `/inventario`** (`lab12_carga_ruta=inventario`),
como en la página. El `ServiceEntry` del Lab 8 usa `exportTo: [".", "gateway-<lab_id>"]`
para hacerlo visible solo a la app y al Gateway propios, incluso cuando varios
participantes usan el mismo host externo. El validador exige el hostname real
como `destination_service_name`, valores de fracción 429 entre 0 y 1 y la alerta
`CuotaAgotada` de ese backend, no una alerta de otra ruta.

`-e lab12_carga_ruta=bank` comprueba explícitamente `bank-api` (cuota 5/min).
Su resumen identifica esa variante; **no prueba el inventario**. Si la consulta
no devuelve series del inventario en `atp-<lab_id>`, revisa `exportTo`, el namespace
del PodMonitor y las etiquetas reales. No cambies entradas de otros participantes.
La colisión de host fue observada en un entorno anterior; en el clúster actual no
había ServiceEntry de inventario al preparar esta ejecución. La atribución real
se comprueba al ejecutar el laboratorio, no se da por supuesta por el manifiesto.

Depende del Lab 8 (`/inventario` con cuota 3/min y `bob` con rol `inventario`) y del
`PodMonitor` `istio-pod-monitor` que crea Kuadrant con `spec.observability.enable`.

## Opcionales

| Variable | Qué hace | Alcance |
|---|---|---|
| `lab12_diagnostico: true` | Paso 10: Gateway `diag-` **ClusterIP** (sin ELB) y los cuatro fallos (DNSProviderError, emisor inexistente/no listo, TargetNotFound, Overridden); comprueba cada `status` y **borra todo `diag-*`** al terminar, falle o no | Solo los namespaces del participante |
| `lab12_demos: true` | Pasos 2, 3, 5, 6 y 7: Authorino a 0 (500), Limitador a 0 (sin cuota), 2 réplicas en memoria, Redis compartido y restauración | **TODO el clúster** |

## Riesgo de `lab12_demos`

Las demostraciones modifican los CR `Authorino` y `Limitador` de `kuadrant-system`,
compartidos por **todos** los participantes:

- Mientras Authorino está a 0, **todas** las APIs con AuthPolicy del clúster responden
  `500` (falla cerrado).
- Con Limitador a 0 o con dos réplicas en memoria, **ninguna** cuota del clúster se
  aplica bien (falla abierto / contadores por pod); al pasar a Redis se reinician
  los contadores de todos.

Úsalas solo con el clúster en exclusiva. El bloque `always` intenta por separado
restaurar `spec.replicas` de ambos CR y `spec.storage` de Limitador, esperar los
Deployments y retirar Redis. Si una recuperación falla, intenta las demás y
reporta el fallo; no acredita una restauración completa. Los campos normalmente
ausentes corresponden a una réplica y contadores en memoria. Si el playbook se
interrumpe con Ctrl+C, comprueba a mano:

```bash
oc -n kuadrant-system get authorino authorino -o jsonpath='{.spec.replicas}{"\n"}'
oc -n kuadrant-system get limitador limitador -o jsonpath='replicas={.spec.replicas} storage={.spec.storage}{"\n"}'
```

## Paso 11: HA de Authorino (opt-in independiente)

El playbook `lab12-authorino-ha.yml` requiere `lab12_authorino_ha=true`,
`lab12_authorino_ha_exclusivo=true`, gestor Ansible y `lab12_demos=false`.
Ejecutarlo solo cuando no hay otra carga ni demostración global. Usa el estado
bank/JWT restaurado del Lab4A; no usa la variante gold ni cambia Limitador.

Comprueba tres pods Ready en tres nodos, sus EndpointSlices y el clúster Envoy
STRICT_DNS/ROUND_ROBIN con HTTP/2 sobre el Service ClusterIP. Tras una ventana
limpia refresca el JWT y envía **300 llamadas, 20 workers**, sin retries: exige
5 respuestas 200 con el contrato JSON compartido y 295 respuestas 429 en menos
de 60 segundos. El módulo finito mantiene credenciales en argumentos protegidos,
respeta HTTPS_PROXY y usa el certificado autofirmado del laboratorio.

Compara `rq_total` de Envoy antes/después (incremento mínimo 300) y los contadores
por UID de pod. `auth_server_authconfig_total` cuenta authconfigs enforced: exige
incremento, pero no lo identifica con exactamente 300 RPC ni exige reparto igual.
El bloque `always` restaura réplicas y comprueba el UID y **spec completo original**;
si alguien cambió otros campos, falla en lugar de ocultar esa divergencia.

Desde `automation/ansible`:

```bash
ansible-playbook playbooks/lab12-authorino-ha.yml -e lab12_authorino_ha=true -e lab12_authorino_ha_exclusivo=true
```

Esto es cobertura implementada; el resultado real requiere ejecutar el playbook.


## Limpieza

`tasks_from: limpiar` borra la `PrometheusRule` y cualquier resto `diag-*`. El
`RoleBinding` pertenece al rol `tenant`.
