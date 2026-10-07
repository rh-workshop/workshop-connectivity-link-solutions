# Cobertura de validación

El catálogo describe rutas y dependencias; no constituye evidencia de un clúster.
Los wrappers conservan las comprobaciones en `tasks/validar.yml` cuando aplica;
Lab00 verifica el acceso en `tasks/main.yml` y mantiene la navegación UI separada.
Los reportes del runner se guardan fuera de Git y no publican hosts ni credenciales.

## Verificaciones offline

- Suite automation: 251 pruebas PASS con fixtures locales e I/O simulado,
  sobre la fuente final congelada: incluye scope y cache Argo CD, convergencia
  pareada del controlador, validación del sync y demos/HA de Lab12.
  Estos resultados no certifican comportamiento de clúster.
- Catálogo: 16 entradas, rutas, roles importados en orden y etiquetas de limpieza.
- Render: 50 plantillas, 55 escenarios y 114 recursos con fixtures sintéticas.
  Comprueba estructura YAML básica; no schemas CRD, certificados válidos ni admisión.
- Paridad: 70 recursos publicados, comparando todos los campos YAML; 42 de 50
  plantillas. Las ocho restantes tienen exclusiones explícitas con motivo y no
  cuentan como PASS; las variantes no seleccionadas tampoco quedan certificadas.
- Runner: comandos simulados; orden, permisos privados, rechazo de demos globales
  y estados de ejecución. Estas pruebas no sustituyen Ansible en un clúster.
- Demos globales de Lab12: ocho pruebas con I/O simulado cubren el almacenamiento
  inicial, cuotas exactas/replicadas, cuerpos JSON y recuperación independiente
  de los componentes. Un fallo de recuperación intenta las otras restauraciones
  y deja el resultado fallido; esta cobertura no acredita una demo en el clúster.

## Estado por laboratorio

### Recorrido literal del alumno

La cobertura runtime de la tabla corresponde a comprobaciones de los wrappers e
inspecciones complementarias. **No certifica la ejecución literal, en orden, de
todos los comandos publicados con una cuenta de alumno.** Esa revisión está en
curso y registra por separado la preparación del instructor, los pasos de consola,
los comandos ejecutados, sus resultados y las correcciones repetidas.

La primera comprobación de prerrequisitos detectó que la página del Lab 0 solicita
el proveedor `workshop`, mientras el clúster ofrecía solamente `local-admin` y el
instalador utilizaba `workshop-htpasswd`. El recorrido del alumno no se considera
aprobado hasta corregir la preparación y comprobar el login publicado.

Avance del recorrido literal (2026-10-07, variante AWS):

- Lab 0: PASS tras preparar una cuenta nueva sin privilegios administrativos.
  Consola y CLI comparten identidad; ambos proyectos están activos. Se obtuvo
  el token por la interfaz y se ejecutaron los bloques publicados, con
  las sustituciones indicadas para los datos del instructor y la confirmación
  TLS interactiva. Un fallo del capturador local se conserva como intento del
  ejecutor, sin atribuirlo al laboratorio ni convertirlo en PASS.
  La sesión Bash activa `pipefail` para detectar fallos de comandos anteriores
  al último proceso de un pipeline; el comando se comprobó en la sesión del alumno.
- Lab 1: siete bloques de consulta ejecutados con código cero y condiciones
  esperadas. La comprobación de consola detectó el complemento desplegado pero
  deshabilitado. Se ejecutó su habilitación publicada como preparación del
  instructor y se repitió la vista UI: PASS en el proyecto propio, con listas
  vacías y sin `Access Denied`. Se corrigió la página para seleccionar el proyecto
  del alumno y recargar; no se ampliaron sus permisos a otros participantes.
- Lab 2: PASS en los cinco bloques del recorrido y en la lista GatewayClass de
  la consola: controlador Istio y `Accepted=True`. Se corrigió el acceso UI para
  utilizar Home → Search cuando Networking no ofrece ese menú.
- Lab 3: PASS en la rama AWS: Gateway aceptado/programado, balanceador asignado,
  Certificate listo, políticas TLS/DNS aplicadas y JWT esperando la HTTPRoute.
  La consola del alumno mostró las tres políticas y sus estados esperados.
  La alternativa Route passthrough no se ejecutó.
- Lab 4A: PASS del recorrido obligatorio AWS tras corregir la entrada de
  plataforma y repetir los comandos publicados. La comprobación OIDC detectó fallo DNS del transporte local
  aunque el pipeline devolvía cero; se conservó como fallo semántico. Tras corregir
  el proxy local se repitió el comando publicado y se verificó el documento OIDC.
  La primera petición con JWT válido devolvió HTTP 500; no se cuenta como PASS
  aunque curl terminara con código cero. Las repeticiones dieron 401 sin token,
  401 con token inválido y 200 con el JSON Party esperado. La cuota exacta pasó:
  cinco respuestas 200 y dos 429. Los controles con emisores nuevos conservaron
  el fallo inicial, incluso ampliando temporalmente el timeout a dos segundos;
  ese cambio se revirtió en la fuente y mediante Argo CD. El gate del operador
  pasó después de la restauración y el Gateway volvió a 200 ms.
  Las pruebas de red desde Authorino y dos routers detectaron el patrón de
  hairpin del NLB: falla la dirección de la propia zona y responde la otra.
  Los atributos y destinos de AWS coinciden con esa limitación de preservación
  de IP del cliente. Se aplicó la excepción mediante OpenTofu: únicamente el
  grupo HTTPS dejó de preservar la IP del cliente. La comparación completa
  confirmó HTTP80 y demás atributos intactos, además del Gateway del alumno y
  su balanceador separado. Después, doce consultas desde Authorino y ambos
  routers hacia las dos direcciones pasaron con HTTP 200, TLS válido y contratos
  OIDC/JWKS correctos; conectar tardó entre uno y cuatro milisegundos.
  Consola, OAuth y Keycloak conservaron sus respuestas y TLS válido en nueve
  controles adicionales. La IP observada por el router/Keycloak cambia a la del
  NLB; se revisó que no hubiera controles actuales de IP/cuota dependientes de
  ella. Una primera petición con un emisor nuevo devolvió 200 y JSON válido,
  pero se ejecutó antes de completar su gate previo; no acredita el control
  completo. Un segundo emisor nuevo pasó el gate previo de rutas, políticas,
  AuthConfig, WASM activo y sincronización xDS: su primera petición, sin
  reintento, devolvió 200 y JSON válido en 0,45 s. Se repitieron los comandos
  del alumno: renovación de JWT, 401 sin token, 401 inválido, 200 con JSON,
  política Enforced y cinco 200 seguidos de dos 429 tras esperar 61 s.
  La anotación de Keycloak que reemplaza las cabeceras reenviadas se aplicó
  mediante Argo CD únicamente a su fase. Se comprobaron los propietarios
  CR → Ingress → Route y los set-header efectivos en ambos routers.
  No se ejecutaron todas las ramas opcionales de diagnóstico.
  Los fallos de selección de pods y normalización del hostname
  del capturador suplementario se conservan como errores del ejecutor, no PASS.
- Lab 4B: PASS en sus 31 bloques, ejecutados en orden en la misma sesión.
  API key ausente o inválida: 401; clave válida: 200 con JSON Party;
  rol customer en `/admin`: 403; tras recrear el Secret con rol admin: 200.
  Restaurado customer, la cuota dio cinco 200 y dos 429. Eliminar la clave
  dio 401; eliminar la AuthPolicy de ruta y renovar el JWT devolvió 200.
  Se conservaron Gateway, backend y RateLimitPolicy para los siguientes labs.
- Labs 5–12 y Bonus: pendientes en esta pasada literal.

| ID | Render de plantillas | Paridad con AsciiDoc | Runtime de esta revisión |
|---|---|---|---|
| `lab00` | Sin plantillas; bcrypt/CAS y guards probados offline | No aplica: alta en IdP existente | PASS: alta HTPasswd, login CLI y siete comprobaciones RBAC; consola, proyectos y token desde UI |
| `lab01` | No aplica: inspección | No aplica | PASS confirmado por la sesión principal |
| `lab02` | No aplica: inspección | No aplica | PASS confirmado por la sesión principal |
| `lab03` | Cubierto | Gateway, TLSPolicy, DNSPolicy y AuthPolicy; Route pendiente | PASS: entrada LoadBalancer y referencias del listener al Secret emitido por el Certificate |
| `lab04a` (`lab04`) | Cubierto | Cuatro recursos publicados | PASS: 401 sin token/inválido, JSON Party y cuota exacta 5×200→429 |
| `lab04b` | Cubierto | AuthPolicy y Secret API key | PASS: API key, roles 403/200, JSON Party/AuditLog, cuota exacta 5×200→429 y restauración JWT |
| `lab05` | Cubierto, incluidas ramas OperatorGroup | Telemetry; plataforma clasificada aparte | PASS: HTTP/JSON, logs correlacionados, incrementos 200/401/429 y trazas frescas de Gateway y políticas con request-id y ancestry |
| `lab06` | Cubierto, scripts canónicos como archivos | Application y RateLimitPolicy | PASS: commit 5→20, self-heal de 1→20, revert a 5 y política Enforced; repo efímero |
| `lab07` | Cubierto | Cuatro recursos publicados | PASS: LoadBalancer, DNS autoritativo, certificado ACME y HTTPS/JSON; limpieza y retirada del balanceador confirmadas |
| `lab08` | Cubierto | Cinco recursos publicados | PASS: Gateway→API externa, 403/200, JSON/Host/Authorization, cuota exacta 3×200→429 y restauración del rol temporal |
| `lab09` | Cubierto, Secret con/sin plan_id | Ocho recursos publicados | PASS: user_key, JSON Party/Accounts, cuotas exactas 2/5/5/20→429; gold sin entrada en la política y muestra finita de 21×200 |
| `lab10` | Cubierto | Nueve recursos publicados | PASS: JSON completo, scopes GET/POST, canary, versión forzada, deprecación; override global con cuota exacta 2×200→429 en gobierno y bank-api, y retirada |
| `lab11` | Cubierto, socios JWT/IP | Quince recursos publicados | PASS: IP exacta/XFF falsificada, mTLS/CN, JWT, allowlist/denylist, override y retirada; rechazo mTLS identificado por alerta de negociación TLS, distinto del 403 HTTP, y control positivo 200; DNS remoto de ambos hosts |
| `lab12` | Cubierto, diagnóstico base/emisor no listo | Doce recursos publicados | PASS: métricas del backend elegido, fracción 429 finita y alerta CuotaAgotada; diagnóstico opcional del tenant con condiciones esperadas DNSProviderError, emisor inválido/no listo, TargetNotFound y Overridden, y limpieza de `diag-*` confirmada. Demos globales de fallo, memoria/Redis, HA con tres réplicas y restauración PASS |
| `bonus-ia` | Cubierto | Cuatro recursos publicados | PASS: contrato JSON de consumo, límite efectivo de 100 tokens/60 s, corte 429 y nueva ventana con varios 200 antes del corte |

La sesión principal confirmó la plataforma preparada y la configuración del realm
de Keycloak. Los PASS de Labs 1 y 2 son inspecciones, no pruebas HTTP. El Lab 4A
detectó un rechazo de Route53 a los TXT de propiedad del operador DNS. La corrección
se aplicó mediante OpenTofu, conservando usuario y clave y añadiendo una política
administrada y su asociación. Los Labs 4A y 4B completaron sus comprobaciones
HTTP y de contenido el 2026-10-06, con las mismas credenciales DNS. La red local
rechaza consultas DNS directas: los cuatro servidores autoritativos se comprobaron
desde el clúster (respuesta autoritativa y CNAME esperado), manteniendo además
las pruebas HTTPS del ejecutor. El Lab 0 comprobó login CLI del participante,
permisos de su tenant y rechazo de operaciones administrativas. También pasó
el recorrido por la consola, la visualización de ambos proyectos y la obtención
del token desde la interfaz, comprobado después con `oc whoami`.
El Lab 5 completó su wrapper con código cero, comprobando señales nuevas del
ensayo y la relación de spans `wasm-shim/kuadrant_filter → Authorino/Check`,
con request-id coincidente con el HTTP 401 del ensayo. El Lab 6 comprobó el ciclo
GitOps completo y su limpieza posterior detuvo la reconciliación de ese ejercicio,
conservando la política de cuota para los siguientes laboratorios.

La cobertura runtime comprende 15 rutas únicas de laboratorio (Lab00–12,
Lab04A/4B y Bonus) en las variantes seleccionadas del entorno AWS, más el
diagnóstico opcional, las demos globales y HA de Lab12 descritas abajo. No se
validó la variante on-premise/MetalLB ni todas las ramas de cada laboratorio.
La emisión y el servicio TLS comprobados no acreditan una renovación forzada
ni fallos de un certificado real ya emitido; los diagnósticos de emisor
inválido/no listo son pruebas distintas.

## Handoff real de plataforma a Argo CD

La sesión principal confirmó PASS final de las nueve fases canónicas. Cada
operación manual nueva terminó `Succeeded` en el SHA inmutable aprobado;
las nueve Applications quedaron `Synced`/`Healthy`, conservaron su UID y
pasaron sus gates nativos. No quedaron operaciones activas, auto-sync ni
prune; los 44 recursos deseados conservaron `Prune=false,Delete=false`.
La comparación exacta por recurso confirmó no-op funcional del SHA aprobado,
sin sustituir la configuración existente por un spec parcial.

- Gate SSA final: código cero, `ok=true`, 70 registros (44 deseados y 26
  prerrequisitos externos). Los 34 negativos devolvieron `allowed=false`;
  la conexión local mantuvo su scope de 14 namespaces y el contrato del Secret.
- Preflight de cache: los 266 pares tipo/namespace pasaron autorización
  `list/watch` y LIST real. Es lectura finita; no concede escrituras nuevas.
- Verificación Ansible en modo gestor Argo CD: código cero, `ok=57`,
  `changed=0`, `failed=0`.
- Prueba negativa de propiedad: una escritura Ansible se rechazó por el guard,
  con código dos, `ok=21`, `changed=0`, `failed=1`. Es el rechazo esperado,
  no una reconciliación fallida que se haya ignorado.

Se conservan también los intentos fallidos: la primera comprobación del reinicio
terminó con código dos al revertir el operador la anotación temporal del template;
la recuperación privada y la comprobación final pasaron. El primer gate de
gateway-defaults usó el gestor Ansible y rechazó la propiedad Argo CD; se repitió
explícitamente como consulta con `plataforma_gestor=argocd` y código cero. Ningún
fallo inicial se transforma retrospectivamente en PASS.

La revisión arquitectónica aceptó este perfil y SHA; el perfil privado quedó
con `plataforma_gestor=argocd`. La evidencia acredita adopción manual de recursos
existentes, sin publicar inventarios ni credenciales; no prueba autorreparación
automática ni recreación de recursos borrados.

## Cómo actualizar la evidencia

Ejecuta los checks documentados en [README.md](README.md), después el runner con
valores privados y `--execute` para los labs autorizados. Registra únicamente lo
comprobado: fecha, procedimiento, exit code y alcance. Un exit code cero del
wrapper no demuestra todas las ramas, todas las operaciones HTTP ni las demos
opcionales. Conserva logs y reportes privados; actualiza esta matriz a partir de
ellos, sin copiar datos del entorno ni afirmar que una fixture prueba runtime.

El Lab 12 requiere observabilidad del Lab 5 aunque no lo importe. Las demos
globales (`lab12_demos`) permanecen excluidas del runner ordinario porque afectan
a todo el clúster. El usuario confirmó que el clúster actual es exclusivamente
suyo y autorizó su ejecución separada. La sesión principal confirmó código cero
en el ensayo real de fallo y almacenamiento:

- Authorino a cero: HTTP `500`; después de restaurar, `200` con el JSON esperado.
- Limitador a cero: seis respuestas `200`, demostrando el fallo abierto.
- Dos réplicas con memoria: seis `200` y seis `429` en esa muestra. Ese reparto
  observado no garantiza seis admisiones en otras conexiones.
- Dos réplicas con Redis: cuota exacta de tres `200` seguidos de un `429`.
- Restauración: UID y spec completos de Authorino y Limitador iguales a los
  snapshots iniciales; no quedan Deployment, Service ni Secret del Redis de demo.

La demostración HA de Authorino también completó su ejecución real con código
cero: tres réplicas Ready en nodos distintos y 300 peticiones con concurrencia
20 produjeron exactamente cinco `200` con JSON válido y 295 `429`, en unos 14 s.
Envoy incrementó `rq_total` de 1012 a 1312 y `cx_total` de 7 a 9; `cx_active`
pasó de cero a dos. Los incrementos por pod fueron `0 / 147 / 153`, ilustrando
el reparto por conexiones persistentes, no un resultado fijo por réplica.
La restauración conservó el mismo UID y spec completo inicial.

La evidencia de estos ensayos está en logs privados; las fixtures offline
siguen siendo evidencia independiente. El PASS del handoff de plataforma
corresponde a las operaciones reales y gates registrados arriba; el render,
el dry-run o los PASS de laboratorios por sí solos no lo acreditan.

Lab00 dispone del wrapper de acceso del instructor, con verificación de sólo
lectura por defecto; login y navegación UI siguen como recorrido separado.
Un PASS de ese wrapper no demuestra la consola ni el token. El alias `lab04`
remite a la implementación de Lab04a.
