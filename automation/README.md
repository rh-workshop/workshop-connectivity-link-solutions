# Automatización del taller Red Hat Connectivity Link 1.4.3

Levanta los laboratorios del taller **por separado** y de forma idempotente con
Ansible, para preparar un clúster, reproducir un lab o dejar a un participante en
el punto de partida de cualquier laboratorio.

- **Ansible** (`ansible/`): plataforma, participante (tenant), realm de Keycloak y
  cada laboratorio como un rol independiente.
- **OpenTofu**: infraestructura AWS fuera de OpenShift. Una fuente por capacidad:
  VM externa y VPC del Lab 8 en [`labs/lab08/opentofu/`](labs/lab08/opentofu/README.md);
  credenciales DNS del tenant, IAM Route 53, ACME DNS-01 del ingress y subredes del
  Gateway en [`common/opentofu/`](common/opentofu/). Estado, planes y variables reales
  quedan fuera de Git.

Cubre la plataforma, Keycloak, los Labs 1 a 12 y el Bonus, cada uno validado en
un clúster OpenShift 4.22 en AWS con RHCL 1.4.3. Para añadir un laboratorio nuevo,
sigue el patrón de [«Añadir un laboratorio»](#añadir-un-laboratorio).

## Requisitos

| Herramienta | Versión probada |
|---|---|
| `ansible-core` | 2.21 |
| Colecciones | `kubernetes.core` 6.5, `community.general` 13.2, `community.okd` 5.0, `ansible.posix` 2.2, `amazon.aws` 11.4 |
| Python (el de Ansible) | `kubernetes` 36, `dnspython`, `jmespath` |
| Sesión `oc` | `cluster-admin` (kubeconfig activo: `$KUBECONFIG` o `~/.kube/config`) |

```bash
cd automation/ansible
ansible-galaxy collection install -r requirements.yml
```

Todo se ejecuta **desde `automation/ansible/`** (ahí está `ansible.cfg`) y contra
`localhost`: los módulos hablan con la API de OpenShift y con Keycloak.

> **Barrera de seguridad.** `openshift_api_esperada` (en `group_vars/all.yml`)
> hace fallar cualquier playbook si el kubeconfig activo apunta a otra API. Con
> varios clústeres en `~/.kube/config`, exporta `KUBECONFIG` explícitamente.

## Uso rápido

```bash
cd automation/ansible
export KUBECONFIG=~/.kube/workshop          # kubeconfig del clúster del taller

ansible-playbook playbooks/plataforma.yml                       # verifica la plataforma (no escribe)
ansible-playbook playbooks/lab04b.yml -e lab_id=user7           # deja a user7 al final del Lab 4B
ansible-playbook playbooks/limpieza.yml -e lab_id=user7         # borra todo lo de user7
ansible-playbook site.yml -e lab_id=user7                       # secuencia completa definida en site.yml (incluye labs avanzados)
```

## Laboratorios, playbooks y dependencias

La plataforma usa un controlador Argo CD dedicado; Lab 6 conserva su instancia
y repositorio propios. Para preparar el árbol por componentes, publicar un SHA
revisado y transferir propiedad fase a fase, seguir la
[entrada operativa de adopción](scripts/README-adoption.md#entrada-operativa).
Namespaces y RBAC existentes quedan fuera de desired state. El perfil completo
revisado proyecta `44` recursos en nueve fases; otros perfiles pueden variar.
Las nueve fases pasaron el sync manual y los gates reales del perfil revisado,
según [VALIDATION.md](VALIDATION.md). Una validación offline por sí sola no
acredita el handoff de otro perfil o SHA.

Cada `playbooks/labNN.yml` importa por sí mismo sus prerrequisitos. Como todos
los roles son idempotentes, ejecutar el Lab 4B en un clúster con solo la
plataforma crea el tenant, el realm, el Lab 3 y el Lab 4A antes. Los
prerrequisitos se ejecutan **sin su validación** (`<rol>_validar: false`); solo
se valida el lab pedido.

| Lab | Playbook | Importa (en orden) | Contrato del wrapper | Tiempo histórico* |
|---|---|---|---|---|
| Plataforma | `plataforma.yml` | `comun`, `plataforma` | CSVs `Succeeded`, `Istio` Ready, GatewayClass Accepted, `Kuadrant` Ready, ClusterIssuer Ready, `Keycloak` Ready, ClusterRoles del taller | 17 s (verificar) · 28 s (modo instalar, todo presente) |
| Tenant | `tenant.yml` | `comun`, `tenant` | Namespaces con `gateway-tenant`, Secret DNS en `gateway-<id>` | 20 s |
| Keycloak | `keycloak.yml` | `comun`, `keycloak_realm` | Discovery OIDC, `iss` del token de alice, rol `customer` sin `inventario` | 23 s |
| 0 | `lab00.yml` | `comun`, `lab00` | IdP/Secret explícitos y entrada HTPasswd; alta/rollback sólo con opt-in y backup privado. RBAC del tenant y recorrido UI se validan aparte | No medido |
| 1 | `lab01.yml` | `comun`, `lab01` | 4 CSVs de RHCL + OSSM `Succeeded`, `Kuadrant` Ready, Authorino y Limitador Running, CRDs de política | 11 s |
| 2 | `lab02.yml` | `comun`, `lab02` | GatewayClass, controlador y `Accepted` | 4 s |
| 3 | `lab03.yml` | `comun`, `tenant`, `keycloak_realm`, `lab03` | Gateway Programmed con dirección, Certificate Ready, Secret TLS, TLSPolicy y DNSPolicy `Enforced`, AuthPolicy JWT `Accepted` | 47 s (ya creado) |
| 4A | `lab04a.yml` | … `lab03`, `lab04a` | HTTPRoute Accepted/ResolvedRefs, DNSRecord Ready, AuthPolicy y RateLimitPolicy `Enforced`, DNS resuelve; **401** sin token, **401** token inválido, **200** con JWT de alice, **429** al agotar la cuota | 58 s (ya creado) |
| 4B | `lab04b.yml` | … `lab04a`, `lab04b` | **401** sin clave / clave incorrecta, **200** con clave, **403** rol customer en `/admin`, **200** rol admin, **429** cuota; revoca la clave (**401**) y restaura el JWT (**200**) | ver abajo |
| 5 | `lab05.yml` | … `lab03`, `lab04a`, `lab05` | Plataforma de observabilidad (solo verificación; `lab05_plataforma_verificar_solo=false` crea lo que falte sin tocar lo existente); access log JSON con **401** y **429** y sin 200 (filtro `Telemetry`); `istio_requests_total` del Gateway en Thanos con 200/401/429; trazas del Gateway en Tempo | 3 min 31 s desde cero · 85 s repetido |
| 6 | `lab06.yml` | … `lab03`, `lab04a`, `lab06` | Application Synced/Healthy; commit 5→20 aplicado, cambio manual a 1 deshecho por self-heal, `git revert` a 5; RLP gestionada por Argo CD y `Enforced`. Repo efímero en el clúster (`lab06_git_modo=local`) o el del participante (`externo`, push opcional con credencial de vault) | 3 min 47 s · 95 s |
| 7 | `lab07.yml` | … `lab03`, `lab04a`, `lab07` | Segundo Gateway con ELB, DNSPolicy `Enforced` y DNSRecord Ready en la zona pública, Certificate ACME Ready; **200 con `validate_certs: true`** (curl sin `-k`). Se omite con `entrada_modo=route` | 4 min 49 s · 71 s |
| 8 | `lab08.yml` | … `lab04a`, `lab08` (exige `lab08_ext_host`) | ExternalName + ServiceEntry, ruta y políticas Enforced; **401** sin token, **200** bob sin reenviar `Authorization`, **403** alice antes de asignar el rol `inventario`; ventana limpia: cuota configurable (por defecto tres **200** con JSON válido y cuarto **429** en menos de 60 s); bank-api **200** y rol retirado al terminar | 3 min 28 s · 1 min 28 s |
| 9 | `lab09.yml` | … `lab04a`, `lab09` | **401** sin clave/clave inválida, **200** clave original; ventanas limpias: bronze dos **200** y tercer **429**, básico/silver cinco **200** y sexto **429**, premium veinte **200** y siguiente **429**; JSON de cada **200**. Gold: configuración sin entrada de cuota y muestra finita de 21 respuestas **200**; **404** sin mapping rule y CORS | 3 min 29 s · 1 min 33 s |
| 10 | `lab10.yml` | … `lab04a`, `lab10` | Scopes M2M; GET read **200**, POST read **403**, POST write **200**, alice **403**; techo `overrides` → `Overridden`: gobierno y bank-api prueban cada uno una ventana limpia con techo configurable (por defecto dos **200** con JSON válido y tercer **429**); retirada → `Enforced`; canary 90/10 (2–30 % de v2), `x-api-version: v2`, `Deprecation`/`Sunset` solo en v1 | 4 min 23 s · 2 min 18 s |
| 11 | `lab11.yml` | … `lab04a`, `lab11` (otro ELB) | PROXY protocol (IP real), allowlist/denylist/rangos/IP+JWT, override `merge`, AuthorizationPolicy de Istio, mTLS en dos capas (fallo TLS / **403** / **200**) | 5 min 54 s · 2 min 39 s |
| 12 | `lab12.yml` | … `lab04a`, `lab08`, `lab12` | `can-i` PrometheusRule, regla cargada, PromQL por ruta, `CuotaAgotada` **firing**; opcional `lab12_diagnostico` (`diag-*`); demos que afectan a todo el clúster solo con `lab12_demos=true` | 5 min 15 s · 1 min 40 s |
| Bonus | `bonus_tokens.yml` | … `lab03`, `lab04a`, `bonus_tokens` | **200** con `usage.total_tokens`, **429** al pasar de 100 tokens, ventana renovada; recrea la TokenRateLimitPolicy si su spec cambió (Limitador conserva límites viejos) | 4 min 38 s · 2 min 5 s |

\* Mediciones de una revisión anterior en OCP 4.22 sobre AWS, desde Lima,
anteriores a las comprobaciones estrictas de contenido y cuota. No describen la
duración ni acreditan el resultado de los wrappers actuales; sus evidencias se
registran en `VALIDATION.md`. Lab 4B desde cero: ver «Tiempos históricos» al final.

Labs 1 y 2 son de inspección: no crean nada y su «ejecución» es la validación.

### Etiquetas

| Etiqueta | Efecto |
|---|---|
| `plataforma`, `tenant`, `keycloak`, `lab01` … `lab12`, `bonus_tokens` | Ejecuta solo ese rol dentro del playbook (`comun` corre siempre) |
| `validar` | Selecciona tareas etiquetadas de validación; puede omitir hechos y prerrequisitos necesarios. Las comprobaciones pueden modificar recursos: para repetir un lab, usa su wrapper completo |
| `limpieza_lab12` … `limpieza_lab05`, `limpieza_bonus_tokens`, `limpieza_lab04b`, `limpieza_lab04a`, `limpieza_lab03`, `limpieza_keycloak`, `limpieza_tenant` | En `limpieza.yml`, limpia solo esa parte |

Ejemplos:

```bash
ansible-playbook playbooks/lab04a.yml -e lab_id=user7 --tags lab04a            # solo el rol del Lab 4A
ansible-playbook playbooks/lab04a.yml -e lab_id=user7                          # repetir con hechos y prerrequisitos
ansible-playbook playbooks/lab04b.yml -e lab_id=user7 -e lab04b_restaurar_jwt=false  # deja la ruta con API key
ansible-playbook playbooks/lab04b.yml -e lab_id=user7 -e lab03_validar=true    # valida también un prerrequisito
```

## Validación por laboratorio

Los IDs del catálogo son `lab00`, `lab01`, `lab02`, `lab03`, `lab04a`,
`lab04b`, `lab05` … `lab12` y `bonus-ia`. `lab04` es alias de `lab04a`;
Lab00 tiene un wrapper opcional de acceso para el instructor; login y navegación
UI son un recorrido separado. Lista y planifica desde la raíz, sin ejecutar Ansible:

```bash
python3 automation/scripts/validate_labs.py --list
python3 automation/scripts/validate_labs.py --labs lab04b,lab03,lab04a
python3 automation/tests/contracts/validation_runner.py
```

El runner ordena los labs solicitados según sus dependencias. El Lab 12 requiere
también la observabilidad del Lab 5; figura como `external_dependencies` porque
su wrapper no ejecuta ese rol. Prepararla antes es responsabilidad del instructor.
Los demás
prerrequisitos los ejecuta cada wrapper existente; no se repiten como wrappers
adicionales. Usa el procedimiento completo **ejecución + validación**;
Labs 1 y 2 son inspecciones. No usa `--tags validar` como atajo universal:
varias comprobaciones dependen de hechos calculados antes y algunas mutan
políticas para probarlas. La ejecución puede crear o modificar recursos.

Para ejecutar, prepara fuera del repositorio un YAML privado (`chmod 600`)
con `lab_id`, `openshift_api_esperada` y los parámetros necesarios para esos
labs. Usa el kubeconfig del destino previsto y consulta los requisitos de cada
README. El Lab 7 exige `entrada_modo` explícito y se marca `skipped` con `route`.

```bash
python3 automation/scripts/validate_labs.py --labs lab01,lab02 \
  --values "$HOME/.config/workshop-cl/values.yml" --execute
```

Sin `--execute`, el reporte marca los wrappers como `skipped`, incluido Lab00.
`manual` corresponde a una entrada sin wrapper. Con ejecución, `passed` significa únicamente exit code cero del
wrapper, `failed` su fallo; tras un fallo, los siguientes quedan `skipped`.
El runner fuerza la validación del rol solicitado y **rechaza `lab12_demos`**:
las demostraciones globales requieren un procedimiento independiente.

Reportes y logs se crean privados (archivos `0600`, directorio `0700`) bajo
`~/.local/state/workshop-connectivity-link/validation/`. `--output-dir` acepta
un directorio nuevo fuera del repositorio. El JSON contiene estados y exit codes,
sin valores privados ni stdout; los logs completos permanecen privados porque
pueden contener información sensible. Un plan o exit code no demuestra códigos
HTTP, todas las ramas del laboratorio ni validación de infraestructura cloud.

## Variables principales

Todas en `ansible/inventory/group_vars/all.yml` (valores de ejemplo del clúster de
desarrollo). Sobrescríbelas con `-e` o con `--extra-vars @mi-entorno.yml`.

| Variable | Ejemplo | Significado |
|---|---|---|
| `lab_id` | `auto` | Participante: `atp-<id>`, `gateway-<id>`, `api-<id>.<zona>`, `realm-<N>` (`user7` → `realm-7`) |
| `openshift_api_esperada` | `https://api.cluster.example.com:6443` | Barrera anti-clúster-equivocado (vacío = sin comprobación) |
| `workshop_zone` | `labs.example.com` | Zona DNS de las APIs; vacío = dominio `*.apps` |
| `entrada_modo` | `loadbalancer` | `loadbalancer` (cloud/MetalLB + DNSPolicy) o `route` (Route passthrough sobre `*.apps`, on-prem) |
| `gateway_class` | `istio` | `istio` (OSSM 3) u `openshift-default` (Gateway API nativo) |
| `tls_issuer_name` | `workshop-selfsigned` | ClusterIssuer de la TLSPolicy |
| `dns_provider_secret` / `dns_provider_tipo` | `dns-provider-aws` / `kuadrant.io/aws` | Secret del proveedor DNS en `gateway-<id>` |
| `dns_provider_secret_origen_namespace` | `gateway-admin` | De dónde se copia ese Secret si no hay `dns_provider_datos` |
| `keycloak_host` | `""` | Vacío = se autodetecta del CR `Keycloak` |
| `plataforma_verificar_solo` | `true` | `true` solo verifica; `false` instala lo que falte |
| `lab04b_restaurar_jwt` | `true` | Termina el Lab 4B revocando la clave y restaurando el JWT (estado que esperan los labs siguientes) |
| `lab05_plataforma_verificar_solo` / `lab05_thanos_token` | `true` / (vault) | Verifica o instala el stack de observabilidad; token para consultar Thanos |
| `lab06_git_modo` | `local` | `local` (repo efímero en el clúster) o `externo` (`lab06_git_repo_url`, `lab06_git_revision`, `lab06_git_path`, `lab06_git_push`, `lab06_git_usuario`/`lab06_git_token` en vault) |
| `lab07_zona` / `lab07_acme_issuer` | `cloud.example.com` / `letsencrypt-dns01` | Zona pública y emisor ACME del Lab 7 |
| `lab08_ext_host` / `lab08_ext_port` | salida de Terraform | Servicio externo del Lab 8 (o `EXT_HOST`/`EXT_PORT` del entorno) |
| `lab11_mi_ip` | autodetectada | IP pública del ejecutor para la allowlist del Lab 11 |
| `lab12_diagnostico` / `lab12_demos` | `false` / `false` | Diagnóstico `diag-*` (solo el participante) / demos que escalan Authorino y Limitador (**todo el clúster**) |
| `bonus_tokens_limite` | `100` | Tokens por minuto del Bonus |

On-prem sin balanceador: `-e entrada_modo=route -e workshop_zone=` (la zona pasa a
ser `*.apps` y no se crea DNSPolicy).

## Plataforma: verificar o instalar sin pisar nada

`playbooks/plataforma.yml` tiene dos modos:

- **`plataforma_verificar_solo: true`** (por defecto en este clúster): solo
  lectura. Falla si falta algo o no está sano.
- **`plataforma_verificar_solo: false`**: crea **solo lo que falte**:
  - Subscriptions de `rhcl-operator`, `servicemeshoperator3`,
    `openshift-cert-manager-operator` y `rhbk-operator`, solo si el namespace no
    tiene ya una Subscription a ese paquete (con cualquier nombre).
  - CRs `IstioCNI`/`Istio`, `Kuadrant` y el ClusterIssuer `workshop-selfsigned`,
    solo si no existen. **Nunca** se modifican: el `meshConfig` de tracing y
    access logs del Lab 5 y la `observability`/`developerPortal` del `Kuadrant`
    quedan intactos.
  - `overrideArgs` de cert-manager (`plataforma_certmanager_dns01_publico: true`),
    solo si no hay ninguno.
  - Keycloak + PostgreSQL, solo si no existe el CR `Keycloak` (exige
    `keycloak_db_password` y `keycloak_admin_password_inicial` por vault).

Validado en el clúster de desarrollo: ambos modos terminan con `changed=0` y el
`resourceVersion`/`generation` de `Istio`, `Kuadrant` y las Subscriptions no
cambia.

## Defaults AWS de la clase Istio

El instructor prepara una sola selección privada `aws_load_balancer_subnet_ids`
y el ConfigMap canónico de [gateway_defaults](common/roles/gateway_defaults/README.md).
Los estudiantes usan los manifiestos del taller sin variables AWS adicionales:
el controlador Istio proyecta la anotación en los Services de todos sus Gateways.
El patch compartido no define `spec.type`, por lo que conserva los Gateways
ClusterIP del Lab 12. Los IDs reales nunca se guardan en Git.

Desde `automation/ansible/`, `playbooks/gateway-defaults.yml` verifica por defecto.
Instalar exige `gateway_defaults_verificar_solo=false` y `plataforma_gestor=ansible`;
con Argo CD solo verifica la fuente GitOps. El rol comprueba versión/Ready,
namespace del plano de control, propiedad de todos los Gateways afectados y
unicidad del ConfigMap. `gateway_defaults_backup=true` guarda estado previo
privado fuera de Git antes de aplicar. La migración de anotaciones explícitas
existentes requiere una operación separada del instructor.

`aws_gateway_subnets_override=false` mantiene desactivadas las anotaciones
por Gateway de Labs 3, 7 y 11, incluso si la lista de subnets está definida.
Solo una excepción deliberada usa `true`; el Lab 11 conserva PROXY protocol.
Los valores privados identifican subnets válidas del entorno; el formato no
certifica que sean públicas ni que su conectividad sea correcta.

## Cabeceras del proxy de Keycloak

El CR canónico conserva `httpEnabled: true` y `proxy.headers: xforwarded` para terminación TLS en el router. Declara `spec.ingress.annotations.haproxy.router.openshift.io/set-forwarded-headers: replace`; el operador traslada la anotación al Ingress y OpenShift a la Route generada. Así el router reemplaza `Forwarded` y `X-Forwarded-For` en esa entrada de Keycloak: el comportamiento `append` conserva valores enviados por el cliente y no establece por sí solo ese límite de confianza. [RHBK 26.6 · Configuración del proxy con el operador](https://docs.redhat.com/en/documentation/red_hat_build_of_keycloak/26.6/html-single/operator_guide/index).

Argo CD gestiona el CR en la fase `keycloak`; los operadores conservan la propiedad del Ingress y la Route. Tras sincronizar, comprueba la anotación en ambos recursos y el acceso OIDC. Este ajuste se limita a Keycloak, sin cambiar la política global del IngressController ni parchear directamente la Route.

## Acceso interno a Keycloak mediante el NLB

Si el NLB del router envía una conexión al mismo nodo que la inicia, la
preservación de IP puede impedir el acceso de Authorino al issuer. El componente
[ingress-hairpin](common/opentofu/ingress-hairpin/README.md) permite revisar y
cambiar únicamente ese atributo del grupo HTTPS existente mediante OpenTofu.
El CCM conserva la gestión del balanceador; no se importa ni se recrea.

Es una preparación excepcional del instructor, no un paso del alumno. Requiere
auditar el uso de IP original en las rutas compartidas, guardar evidencia privada
y comprobar conexiones nuevas y el primer JWT después del cambio. El router
pasará a observar la IP del NLB. El balanceador separado del Lab 11 permanece
fuera del alcance. La verificación sin escrituras y el rollback explícito están
documentados en el componente; un plan OpenTofu no certifica el laboratorio.

## Conectividad hacia DNS autoritativo

`dns_verificar_autoritativos=true` comprueba por defecto todos los servidores
autoritativos sin recursión antes de probar HTTPS desde la máquina de control.
Lab11 usa la misma comprobación para ambos hostnames; su consulta HTTPS a `b2b-*`
presenta el certificado mTLS del socio. Si la red del ejecutor intercepta o
impide consultas DNS directas, el instructor puede fijar explícitamente
`dns_verificar_autoritativos=false` en valores privados **solo después de verificar
manualmente, desde otra ubicación, ambos hostnames contra cada servidor
autoritativo**. Conserva esa evidencia en el registro de ejecución. La excepción
omite únicamente la consulta autoritativa de esta máquina: las conexiones HTTPS
locales siguen siendo obligatorias y deben responder. No la marques como
comprobación autoritativa superada ni uses una respuesta recursiva como prueba.

## Idempotencia

- Recursos del taller: **server-side apply** con `field_manager: workshop-ansible`
  (solo se gestionan los campos declarados).
- Recursos compartidos de plataforma: «comprobar y omitir si existe».
- Keycloak: módulos `community.general.keycloak_*`; la contraseña se fija solo si
  el usuario no puede iniciar sesión (el módulo no puede leerla).
- Esperas reales con `k8s_info` + `until` sobre condiciones (`Succeeded`,
  `Ready`, `Programmed`, `Enforced`, `Accepted`), nunca `sleep`.

Segunda ejecución de `lab04b.yml`: `changed=6`, y los seis son **las acciones
del propio Lab 4B** (crear la clave y la política de ruta, cambiar el rol,
revocar y restaurar el JWT), que se repiten por diseño. Todo lo persistente
(tenant, realm, Gateway, políticas, bank-api) queda en `ok`. Con
`lab04a.yml`, `lab03.yml`, `tenant.yml`, `keycloak.yml`, `lab01.yml` y
`lab02.yml` la repetición da `changed=0`.

Transitorio conocido: justo después de crear el Gateway, la **primera**
repetición puede marcar `changed` en «Crear el Gateway HTTPS» mientras los
controladores aún escriben su `status`; la `generation` sigue en 1 (el `spec`
no cambia) y la siguiente ejecución ya da `ok`.

## Limpieza

```bash
ansible-playbook playbooks/limpieza.yml -e lab_id=user7                          # todo
ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab04b   # solo el Lab 4B
```

Orden: Lab 4B → Lab 4A → Lab 3 → realm → tenant. En el Lab 3 se borra **primero
la DNSPolicy** y se espera a que desaparezca su `DNSRecord` (el DNS Operator
retira el registro de Route 53), luego el Gateway, y se espera a que desaparezca
su Service `LoadBalancer` (libera el balanceador de AWS, que cuesta dinero).
Al final se comprueba que no queda ningún namespace, Service ni
ClusterRoleBinding con `workshop.user=<lab_id>`.

`admin` está en `limpieza_lab_ids_protegidos`: `limpieza.yml -e lab_id=admin`
falla salvo `-e limpieza_forzar=true`.

## Secretos

Ningún secreto vive en el repositorio. Tres fuentes, por orden de preferencia:

1. **ansible-vault** (uso real):

   ```bash
   ansible-vault create ansible/inventory/group_vars/vault.yml   # no lo subas sin cifrar
   ```

   ```yaml
   # contenido (cifrado)
   keycloak_admin_usuario: admin
   keycloak_admin_password: "..."
   keycloak_usuarios_password: {alice: "...", bob: "..."}
   dns_provider_datos:
     AWS_ACCESS_KEY_ID: "..."
     AWS_SECRET_ACCESS_KEY: "..."
     AWS_REGION: us-east-2
   lab04b_api_key: "..."                 # opcional; si falta se genera una aleatoria
   keycloak_db_password: "..."           # solo si plataforma crea Keycloak
   keycloak_admin_password_inicial: "..."
   ```

   ```bash
   ansible-playbook playbooks/lab04b.yml -e lab_id=user7 -e @inventory/group_vars/vault.yml --ask-vault-pass
   ```

2. **Variables de entorno** para Keycloak: `KC_ADMIN_USER` y `KC_ADMIN_PASSWORD`.
3. **Del propio clúster**, si no se da nada: el admin de Keycloak se lee del Secret
   `keycloak-bootstrap-admin` (namespace `keycloak`) y el Secret DNS se copia de
   `dns_provider_secret_origen_namespace`. Requiere `cluster-admin`.

Las contraseñas `alice`/`bob` por defecto son las que publica el material del
taller; en un entorno real se sobrescriben desde vault. Todas las tareas que
manejan secretos llevan `no_log: true`.

## Estructura

```text
automation/
├── catalog.yml                rutas, dependencias, alcance y limpieza por lab
├── labs/lab00 … lab12/        README por entrada (lab04 es alias de lab04a)
│   ├── roles/<rol>/           única implementación: tasks, defaults y templates
│   └── opentofu/              solo lab08: infraestructura externa AWS
├── labs/bonus-ia/roles/bonus_tokens/
├── common/roles/              comun, plataforma, tenant, keycloak_realm
├── scripts/                   comprobaciones offline del catálogo y paridad
├── tests/fixtures/            valores sintéticos para renderizar, sin credenciales
└── ansible/
    ├── ansible.cfg · requirements.yml · site.yml
    ├── inventory/localhost.yml · inventory/group_vars/all.yml
    └── playbooks/             wrappers compatibles y limpieza (sin roles duplicados)
```

Los wrappers siguen ejecutándose desde `automation/ansible/`; `roles_path`
resuelve los roles canónicos de `common/` y `labs/`. El catálogo describe
prerrequisitos importados por los wrappers, no sustituye Ansible ni acredita
una ejecución en clúster. Lab00 conserva el recorrido UI separado de su wrapper
de acceso; Lab04 remite a Lab04a.

Comprobación local desde la raíz del repositorio (Python con PyYAML y Jinja2):

```bash
python3 automation/scripts/check_catalog.py
python3 automation/scripts/check_render.py
python3 automation/scripts/check_parity.py
python3 automation/tests/contracts/catalog_parity.py
python3 automation/tests/contracts/render_contract.py
python3 automation/tests/contracts/aws_subnets.py
python3 automation/tests/contracts/gateway_defaults.py
python3 automation/scripts/check_dns_wait.py            # esperas DNS y casos mTLS del Lab 11
python3 automation/scripts/check_lab10_11_contracts.py   # cuotas exactas (200,200,429) y fallos TLS de Labs 10/11
```

El render usa los defaults de cada rol y `tests/fixtures/render-all.yml` para
hechos sintéticos, con `StrictUndefined`. Cubre todas las plantillas actuales y
ramas de OperatorGroup, planes, socios y diagnóstico. Comprueba objetos YAML,
identidad, namespaces y tipos básicos; no valida schemas CRD ni admisión del API.
Solo permite leer los dos scripts canónicos del Git efímero del Lab 6. La CA y
API key de la fixture son marcadores de demostración y no sirven para TLS o acceso.
`check_render.py --render-dir /tmp/cl-render-all` conserva las salidas por plantilla.

La paridad compara las fuentes reales con plantillas canónicas: Gateway y políticas
del Lab 3; banco, ruta y cuota del Lab 4A; API key y autenticación del Lab 4B;
Gateway, ruta, DNS y TLS del Lab 7; servicio externo, ServiceEntry, ruta y políticas
del Lab 8; migración y cinco claves del Lab 9; gobierno y backends del Lab 10;
backend, políticas, PKI y mTLS del Lab 11; Redis, alerta y diagnóstico del Lab 12;
Telemetry de errores del Lab 5; Application y política Git del Lab 6; mock y cuota inicial de tokens del Bonus. Compara todos los campos YAML con valores
sintéticos, sin omitir spec, nombres, namespaces ni políticas. La fixture selecciona
explícitamente los heredocs cuando hay versiones sucesivas de la misma identidad.
Las ocho plantillas sin comparación directa quedan clasificadas en
`tests/fixtures/content-parity-exclusions.yml`: comandos imperativos, estados finales
con parches, preparación del instructor y Git efímero. No cuentan como paridad PASS.
Las variantes no seleccionadas también quedan fuera de cobertura; esto no demuestra
equivalencia universal. `--fixture` ejecuta una comparación concreta;
`--render-dir /tmp/cl-parity` conserva las salidas sintéticas por fixture para
inspección. Estas comprobaciones no consultan kubeconfig, inventarios ni el clúster.


Consulta [VALIDATION.md](VALIDATION.md) para distinguir cobertura offline,
prerrequisitos externos y ejecuciones efectivamente comprobadas.


## Añadir un laboratorio

Patrón exacto (ejemplo: Lab 5, rol `lab05`):

1. **Rol** `automation/labs/lab05/roles/lab05/`:
   - `defaults/main.yml`: `lab05_validar: true` y los parámetros propios del lab
     (prefijo `lab05_`).
   - `meta/main.yml`: copia el de otro lab y cambia la descripción;
     `dependencies: []` (las dependencias las declara el playbook).
   - `templates/*.yaml.j2`: los **heredocs del `.adoc`** del lab, cambiando
     `${VAR}` por los hechos de `comun` (`{{ lab_id }}`, `{{ wk_ns_app }}`,
     `{{ wk_ns_gateway }}`, `{{ wk_gateway }}`, `{{ wk_lab_host }}`,
     `{{ wk_keycloak_issuer }}`, `{{ wk_realm }}`…). Misma semántica, mismos
     nombres de recurso.
   - `tasks/main.yml`: aplicar con
     `kubernetes.core.k8s` + `state: present` + `apply: true` +
     `server_side_apply: {field_manager: "{{ k8s_field_manager }}"}` +
     `template: x.yaml.j2`; tras cada recurso, esperar con
     `include_role: {name: comun, tasks_from: esperar_condicion}`; al final:

     ```yaml
     - name: Validar el Lab 5
       ansible.builtin.import_tasks: validar.yml
       when: lab05_validar | bool
       tags: [validar]
     ```
   - `tasks/validar.yml`: las mismas comprobaciones que «Comprueba el resultado»
     del `.adoc`, con `comun/probar_http` (código esperado),
     `comun/probar_cuota_exacta` (ventana limpia, N respuestas 200 con cuerpo
     válido y siguiente 429), `comun/token_keycloak` (token de alice/bob) y `assert` con
     `fail_msg` claro.
   - `tasks/limpiar.yml`: `state: absent` de lo que crea el lab, en orden inverso.
     Recursos compartidos de plataforma (el CR `Istio`, el `Kuadrant`…): **no** se
     borran; si el lab los modifica, se hace por server-side apply solo de los
     campos del lab y se documenta en el README.
2. **Playbook** `automation/ansible/playbooks/lab05.yml`: parte de `lab04a.yml`, añade al final
   `- {role: lab05, tags: [lab05]}` y pon `lab04a_validar: false` en el prerrequisito.
   `comun` siempre con `tags: [always]`.
3. **`site.yml`**: añade `lab05` al final de la lista de roles.
4. **`playbooks/limpieza.yml`**: añade un `import_role … tasks_from: limpiar` con
   `tags: [limpieza_lab05]` **al principio** de `tasks` (orden inverso).
5. **Catálogo y README**: registra `automation/catalog.yml` y documenta `automation/labs/lab05/README.md`; actualiza la tabla con dependencias y validaciones. Añade fixtures de paridad para las nuevas plantillas.
6. Valida con un `lab_id` desechable: desde cero, repetición (idempotencia),
   `limpieza.yml` y comprobación de que no queda nada.

Reglas: sin `shell`/`command` salvo que no exista módulo (y entonces con
`changed_when`); nombres de tarea en español; secretos con `no_log: true`;
nada cluster-scoped con nombre fijo por participante sin label
`workshop.user=<lab_id>` (para que la limpieza lo encuentre).

Trampa verificada en ansible-core 2.21: en una tarea con `until`, los argumentos
se evalúan **una sola vez**; un `lookup()` dentro de `set_fact` + `until` repite
siempre el primer valor. Toda espera debe hacerse con un **módulo** que se
re-ejecute (`k8s_info`, `uri`, `wk_dns_autoritativo`…), nunca con un lookup.

Las pruebas HTTP salen de la máquina de control y usan su resolver DNS. Tras
crear el registro, `comun/esperar_dns` espera a que **todos** los NS
autoritativos lo publiquen antes de tocar el resolver local (evita cachear un
NXDOMAIN, 900 s en las zonas de RHDP) y después a que el resolver local lo vea.

## Tiempos históricos

Mediciones de una revisión anterior en OCP 4.22 sobre AWS, desde Lima. Los
resultados corresponden únicamente a esas ejecuciones. Los wrappers actuales
incorporan comprobaciones adicionales y esperas de ventanas limpias de cuota;
esta tabla no estima su duración ni sustituye las evidencias de `VALIDATION.md`.

| Ejecución | Tiempo | Resultado |
|---|---|---|
| `lab04b.yml` **desde cero** (solo plataforma): tenant, realm, Gateway + ELB, certificado, DNS en Route 53, Labs 4A y 4B con todas sus pruebas | **3 min 25 s** | `changed=25`, `failed=0` |
| `lab04b.yml` repetido | 1 min 22 s | `changed=7` (6 acciones propias del Lab 4B + transitorio del Gateway) |
| `lab04a.yml` / `lab03.yml` sobre lo ya creado | 58 s / 47 s | `changed=0` |
| `limpieza.yml` total | 1 min 15 s | sin restos (namespaces, Service LB, CRB, realm, registro DNS) |

De los 3 min 25 s, ~80 s son la propagación DNS del ELB nuevo hasta el resolver
de la máquina de control.
