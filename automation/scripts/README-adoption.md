# Gate de adopción SSA de plataforma

`check_adoption.py` verifica el handoff sin sincronizar ni aplicar cambios reales.
Ejecutarlo después de revisar/bootstrapear el RBAC acotado y antes de cada sync.
Los gates nativos de readiness siguen siendo obligatorios: este control comprueba
identidad, autorización y ausencia de deriva funcional, no sustituye la salud.

```bash
python3 automation/scripts/check_adoption.py \
  --render-dir /private/platform-render \
  --expected /private/expected-adoption.json \
  --report /private/adoption-report-new.json
python3 automation/tests/contracts/adoption_gate.py
python3 automation/tests/contracts/git_source_contract.py
```

El informe debe ser nuevo y estar fuera de cualquier Git; se crea con permisos
`0600`. El perfil esperado también debe quedar fuera de Git y sin permisos de
grupo/otros. El instructor prepara sus expectativas **después de inspeccionar**
los recursos; el gate no genera ni aprueba snapshots automáticamente. Nunca
exportar Secrets ni copiar inventarios/credenciales a un repo o consola pública.

## Contrato del perfil privado

Objeto JSON con estos campos:

- `controller`: `{identity, uid}`: identidad completa de
  `automation/common/platform-argocd.yml` y UID revisado de su ServiceAccount.
  No se admite el controlador predeterminado usado por Lab 6. El gate exige
  `can-i=no` para patch de `kube-system`, creación de Secret en `keycloak`,
  delete de `kuadrant-system`, patch de ConfigMap no inventariado, bind/escalate
  de ClusterRole, TokenRequest de ServiceAccount y SubjectAccessReview, como el
  SA dedicado y sus grupos reales, antes de SSA.
- `cluster_uid`: UID verificado del Namespace `kube-system`.
- `bundle_sha256`: `digest(resources)` del módulo, con los recursos deseados en
  el orden de `components/*/manifests.yaml`. Revisar primero el bundle y su SHA.
- `applications_sha256`: `applications_digest(render_dir)` del módulo, después
  de aprobar repo, rutas y revisiones inmutables. Cambiar cualquier Application
  invalida la expectativa, aunque sus manifiestos proyectados no hayan cambiado.
- `resources`: mapa identidad `apiVersion|kind|namespace|name` → UID existente.
  Debe coincidir exactamente con `adoption-map.json`, sin recursos nuevos.
- `external`: mapa de las identidades de `external-preconditions.json` a
  `{uid, functional}`; `functional` contiene **completos** los campos presentes
  `spec`, `data` y `binaryData` revisados; para RBAC incluye metadata
  funcional, `rules`, `subjects`, `roleRef` y `aggregationRule`. También se compara
  contra la plantilla canónica: aprobar un snapshot divergente no lo autoriza. No basta un subconjunto: se detecta
  configuración desconocida añadida, retirada o modificada.
- `git_source`: `{bundle, revision, repo_url, published_path, repo_server: {name,
  uid}}`. El bundle es el snapshot privado aprobado, no un checkout. El SHA debe
  ser el commit real que contiene las fases, no un placeholder. Se valida el bundle
  con el helper canónico del publisher, se construye cada fase con `oc kustomize`
  local y se compara su contenido completo/identidades con el render. Las Applications
  deben señalar exactamente ese repo, SHA y path por fase, proyecto `cl-platform`
  y destino `https://kubernetes.default.svc`. No se permiten referencias Kustomize
  remotas ni generadores externos. `repo_server` identifica el Pod real existente
  en `cl-platform-argocd`; se verifica UID antes/después de leer con `git ls-remote`
  el ref remoto exacto `refs/tags/releases/<SHA>` desde su contenedor
  `argocd-repo-server`. El gate sólo puede dar PASS después de que el instructor
  publique el snapshot aprobado. No publica ni sincroniza por sí mismo.
- `cluster_configuration`: contrato saneado del Secret de conexión de la instancia
  dedicada: UID/owner ArgoCD UID, server/name, namespaces finitos, clusterResources
  true y SHA256 de otros campos data/metadata. Nunca incluye config, tokens, claves
  ni certificados en texto plano/base64. Usar el snapshot privado revisado; se
  comprueba antes y después de SSA contra el clúster actual.
- `tracking_config`: `{apiVersion: "v1", kind: "ConfigMap", metadata: {name,
  namespace: "cl-platform-argocd"}, uid, data}` del ConfigMap real de Argo CD.
  `data` es el contenido completo revisado. Se admite únicamente
  `application.resourceTrackingMethod: annotation` explícito; métodos `label`,
  `annotation+label` o implícitos quedan bloqueados hasta probarlos. No se cambia
  la configuración global. `application.instanceLabelKey` se registra y todas
  las labels funcionales se comparan, incluso `app.kubernetes.io/instance`.

El clúster, las expectativas externas y el ConfigMap de tracking se leen con el
contexto del instructor. Cada recurso deseado se lee y simula como
`system:serviceaccount:cl-platform-argocd:cl-platform-argocd-application-controller`,
con grupos `system:serviceaccounts`, `system:serviceaccounts:cl-platform-argocd` y
`system:authenticated`. La simulación ejecuta exclusivamente:

```text
oc --as=<ServiceAccount> --as-group=<grupo> ... apply --server-side
  --force-conflicts --dry-run=server --field-manager=argocd-controller -f - -o json
```

`--force-conflicts` se utiliza únicamente dentro del dry-run; no hay comando de
apply real ni migración CSA. El payload incluye el tracking-id exacto y, si está
configurado, installation-id. Se rechaza ownership de otra Application/instalación.

## Qué se compara y qué bloquea

Se compara el JSON API-normalizado completo del recurso vivo y del dry-run:
`spec`, `data`, configuración, almacenamiento, tipos, listas, labels, annotations,
finalizers y ownerReferences. Se excluyen `status` y metadata volátil
(`uid`, `resourceVersion`, `generation`, `creationTimestamp`, `managedFields`,
`selfLink`); el UID se verifica por separado antes y después. Las únicas excepciones
de metadata son tracking-id/installation-id, el histórico last-applied y la
protección **exacta** `Prune=false,Delete=false`. Otras sync-options no se ignoran.
El informe contiene identidades, códigos y rutas de campos; nunca cuerpos/valores.

Bloquean: recurso ausente, acceso denegado, UID diferente, recurso en borrado,
deriva funcional, identidad/contenido cambiado durante la comprobación, Secrets
en desired state, blockers del renderer, SHA de Application vacío/cero/inválido y
expectativas incompletas. Un PASS conserva valor sólo para ese bundle y esa lectura;
no autoriza sincronizar otro SHA ni acredita reconciliación real del controlador.

Prerrequisitos externos preservados: ClusterIssuer ACME de producción Ready,
CertManager con resolvers DNS01 públicos y ConfigMap de UWM habilitado. Se verifica
su configuración completa revisada; no se incorporan automáticamente a GitOps.
El workaround `console_plugin_configuration` sigue siendo una excepción Ansible
explícita sobre un hijo del operador, documentada en `runtime-actions.json`.

Argo CD 3.5.3 usa `ServerSideApply=true` y `ClientSideApplyMigration=false`:
[constantes exactas de gitops-engine en el tag](https://github.com/argoproj/argo-cd/blob/v3.5.3/gitops-engine/pkg/sync/common/types.go)
y [invocación del controlador](https://github.com/argoproj/argo-cd/blob/v3.5.3/controller/sync.go).
No usar `DisableClientSideApplyMigration=true`, que no es la constante de esa versión.

## Secuencia sin SHA ficticio

1. Renderizar componentes privados omitiendo los tres argumentos de Applications
   (`--repo-url`, `--revision`, `--published-path`), incluso en modo interno.
2. Inspeccionar diferencias reales. Exportar **sólo** `components/` y `overlays/`
   bajo el prefijo aprobado (por ejemplo `platform/`) a otra carpeta privada.
   No copiar informes, Apps ni el RBAC bootstrap al árbol publicado.
3. Crear un bundle local con `repository.py bundle` y leer su SHA real con
   `git bundle list-heads <bundle> refs/heads/main`; todavía no hay publicación.
4. Regenerar el render completo con repo exacto, SHA real y prefijo. Preparar
   expectativas privadas después de la revisión del instructor.
5. El instructor revisa/aplica únicamente el acceso bootstrap necesario, publica
   el bundle aprobado y ejecuta el gate SSA con prueba del ref remoto. Ante cualquier
   denial RBAC, no añadir automáticamente `bind`/`escalate` ni permisos amplios:
   resolver la causa o preservar ese recurso fuera de GitOps explícitamente.
6. Sólo después de PASS y de los gates nativos correspondientes, el instructor
   crea las Applications y solicita sync manual de la fase. No omitir la revisión
   ni reutilizar el PASS para otro SHA.

## Entrada operativa

Ejemplos desde la raíz del repositorio. Usar carpetas privadas nuevas fuera de
Git y un perfil revisado con API/UID esperados. Preparar los Secrets mediante el
mecanismo del entorno; nunca copiarlos al árbol publicado.

1. **Preparar.** Renderizar primero sin Applications y revisar manifiestos,
   `handoff-blockers.json`, acciones runtime y prerrequisitos externos:

   ```bash
   python3 automation/scripts/render_platform.py \
     --values /private/platform-values.yml --output /private/platform-review
   ```

   El perfil completo con gateway-defaults e ingress proyecta nueve fases y,
   en el perfil revisado, `44` recursos deseados. Namespaces y RBAC existentes
   quedan fuera: conservar sus UID/configuración. Otros perfiles pueden variar.

2. **Bootstrap y snapshot.** Instalar el controlador dedicado explícitamente;
   revisar el acceso bootstrap antes de aplicarlo. Lab 6 no cambia:

   ```bash
   (cd automation/ansible && ansible-playbook playbooks/platform-argocd.yml \
     -e platform_argocd_operation=instalar -e @/private/platform-values.yml)
   mkdir -p /private/platform-tree/platform
   cp -R /private/platform-review/components /private/platform-review/overlays \
     /private/platform-tree/platform/
   python3 automation/common/roles/platform_git_repository/files/repository.py \
     bundle --source /private/platform-tree --path /private/platform.bundle
   REVISION=$(git bundle list-heads /private/platform.bundle refs/heads/main | cut -d ' ' -f1)
   python3 automation/scripts/render_platform.py \
     --values /private/platform-values.yml --output /private/platform-adoption \
     --repo-url http://cl-platform-git-repository.cl-platform-gitops.svc:8080/platform.git \
     --revision "$REVISION" --published-path platform
   ```

   La URL del ejemplo exige `publication_mode: internal`. El árbol público usa
   su repo HTTPS aprobado. Revisar `access/project-and-rbac.yaml` y las expectativas
   privadas; no aplicar `bootstrap/external-*.yaml` para adoptar recursos ajenos.
   Usar `respectRBAC: normal`. Para una instancia anterior en strict, seguir la
   [transición nativa del controlador](../common/roles/platform_argocd/README.md#scope-de-la-conexión-local):
   `configurar_controlador` respalda/CAS el campo y renueva sólo su StatefulSet
   propio porque el cache 3.5.3 inicializa ese modo al arrancar. Las operaciones
   Application terminadas se permiten; las activas bloquean la transición.

3. **Publicar el snapshot aprobado.** Preparar/verificar el servidor Git con su
   wrapper; sólo `instalar` puede reconciliar su NetworkPolicy propia. Una política
   legacy sin etiqueta requiere comprobar backup, UID/spec y propiedad explícita
   antes de actualizarla; no hay adopción implícita.

   ```bash
   (cd automation/ansible && ansible-playbook playbooks/platform-git-repository.yml \
     -e platform_git_repository_operation=publicar \
     -e platform_git_repository_bundle=/private/platform.bundle \
     -e @/private/platform-values.yml)
   ```

4. **Dry-run SSA y gates.** Con acceso bootstrap aprobado y aplicado por el
   instructor, ejecutar el gate contra el SHA publicado y expectativas inspeccionadas:

   ```bash
   oc apply --server-side -f /private/platform-adoption/access/project-and-rbac.yaml
   python3 automation/scripts/check_adoption.py \
     --render-dir /private/platform-adoption \
     --expected /private/expected-adoption.json --report /private/adoption-report-new.json
   ```

   Este comando simula SSA como el SA dedicado, verifica el ref desde repo-server
   y no aplica desired state. Un denial o deriva bloquea el sync; no ampliar RBAC
   automáticamente. El informe debe ser nuevo para cada ejecución/SHA.

5. **Sync manual por fase.** Después de PASS, crear las Applications revisadas
   sin automated/finalizers. Solicitar una fase y consultar su gate antes de la
   siguiente; ejemplo para `operators`:

   ```bash
   oc apply -f /private/platform-adoption/applications/operators.yaml
   SYNC_ID=$(python3 -c 'import uuid; print(uuid.uuid4().hex)')
   oc -n cl-platform-argocd patch application cl-platform-operators --type merge \
     -p "{\"operation\":{\"info\":[{\"name\":\"validation-run\",\"value\":\"${SYNC_ID}\"}],\"sync\":{\"revision\":\"${REVISION}\",\"prune\":false}}}"
   oc -n cl-platform-argocd wait application/cl-platform-operators \
     --for="jsonpath={.status.operationState.operation.info[?(@.name==\"validation-run\")].value}=${SYNC_ID}" --timeout=180s
   oc -n cl-platform-argocd wait application/cl-platform-operators \
     --for=jsonpath='{.status.operationState.phase}'=Succeeded --timeout=600s
   python3 automation/scripts/check_application_sync.py \
     --application cl-platform-operators --revision "$REVISION" --operation-id "$SYNC_ID" \
     --manifest /private/platform-adoption/components/operators/manifests.yaml \
     --report "/private/operators-sync-${SYNC_ID}.json"
   (cd automation/ansible && ansible-playbook playbooks/platform-gate.yml \
     -e platform_gate_phase=operators -e @/private/platform-values.yml \
     -e plataforma_gestor=argocd)
   ```

   La Application debe conservar el SHA exacto aprobado en `targetRevision`.
   No avanzar si falla un comando: el helper de sólo lectura exige la operación
   nueva identificada por nonce, `Succeeded`/`Synced`, SHA y recursos exactos.
   Un gate nativo puede aprobar recursos ya sanos aunque el sync no haya ocurrido;
   por eso se ejecuta únicamente después de esta prueba de reconciliación.
   En cada gate posterior al sync, pasar `plataforma_gestor=argocd`: permite
   verificar la propiedad transferida sin escribir. El perfil global y bootstrap
   conservan el gestor Ansible hasta completar el handoff de todas las fases.
   Seguir el [orden y gates de las fases](../platform/kustomize/README.md#orden-con-gates-explícitos).
   `keycloak-prerequisites` precede al sync Keycloak; `ingress-reference` es una
   transición TLS separada con autorización y backup. La prueba offline o el
   dry-run no acreditan reconciliación real: el handoff queda pendiente hasta
   observar sync/readiness y conservación de UID/configuración de cada fase.

## Controlador dedicado y bootstrap externo

La identidad única se lee de `automation/common/platform-argocd.yml`; sus
Applications/AppProject viven en `cl-platform-argocd`. Ese namespace/controlador
se prepara por bootstrap, nunca se adopta dentro del árbol de plataforma.
Lab 6 y el controlador predeterminado `openshift-gitops` permanecen separados.
Sus permisos amplios existentes no se restringen añadiendo Roles nuevos.

Todos los Roles, RoleBindings, ClusterRoles y ClusterRoleBindings proyectados
son prerrequisitos **externos**, declarados en `external-preconditions.json` y
`bootstrap/external-rbac.yaml`. El instructor conserva su implementación
canónica y UID; Argo CD no escribe RBAC, tampoco con resourceNames. El acceso
bootstrap generado excluye por completo el API group RBAC. No conceder bind,
escalate ni permisos del default controller al SA dedicado.

El perfil real con ingress y gateway-defaults tiene nueve fases; desaparece la
Application `rbac`. El número de recursos varía con los componentes opcionales.
Bundles/expectativas/reportes antiguos para el controlador predeterminado no
son compatibles: regenerar, inspeccionar y aprobar un SHA nuevo antes de sync.

## Namespaces existentes: sólo lectura

Los Namespaces quedan fuera de desired state y del whitelist del AppProject.
`bootstrap/external-namespaces.yaml` conserva las fuentes originales como referencia
externa, **no** es una orden de apply. El controlador sólo recibe `get` de nombres
finitos y `list/watch` para cache; nunca patch/update/create/delete de namespaces.
Cada contrato externo verifica UID, estado Active, ausencia de borrado y metadata/spec
completos normalizados contra el snapshot privado revisado. No añade ni cambia labels.

Además de los seis negativos base, el gate exige patch/update denegados para **cada**
namespace externo. Bloquea labels `argocd.argoproj.io/managed-by` y
`argocd.argoproj.io/managed-by-cluster-argocd` que apunten a la identidad dedicada,
y RoleBindings admin/cluster-admin hacia su SA o grupos. Estas comprobaciones
acreditan permisos directos acotados en esa lectura; no prueban aislamiento absoluto
del clúster ni restringen otros controladores. Repetir antes/después del bootstrap.

## Excepción efímera de Tempo OpenShift

Si el desired state contiene un TempoMonolithic del API `tempo.grafana.com` con
`spec.multitenancy.mode: openshift`, su webhook requiere crear TokenReviews.
El ClusterRole acotado añade únicamente `create` de `tokenreviews` en
`authentication.k8s.io`, conforme al [rol del proveedor v0.22.0](https://github.com/grafana/tempo-operator/blob/v0.22.0/internal/manifests/gateway/openshift.go#L50-L65).
No concede `system:auth-delegator`, SubjectAccessReviews,
TokenRequests ni acceso a Secrets. Sin ese modo no genera la regla.

La creación de recursos persistentes sigue prohibida. TokenReview es la única
excepción efímera, y pertenece al bootstrap de acceso fuera del bundle adoptado.
El gate incluye negativos para `create serviceaccounts --subresource=token -n keycloak`
y `create subjectaccessreviews.authorization.k8s.io`: ocho base más patch/update
de cada namespace externo (34 en el perfil con 13 namespaces). Repetir después
de revisar/aplicar la única regla bootstrap; no modificar el SHA de plataforma.

## Conexión del controlador al clúster

El Secret existente `<instancia>-default-cluster-config` pertenece al ArgoCD
dedicado. El bootstrap nativo puede ajustar **sólo** `data.namespaces` a la unión
exacta de namespaces externos del render y el namespace propio, y
`data.clusterResources` a true. Esta excepción configura el alcance de conexión:
no añade tokens, labels managed-by ni permisos Kubernetes. Los grants acotados
y los 34 negativos siguen siendo controles separados. No modifica el controlador
predeterminado de Lab 6.

El gate exige identidad/UID del Secret, UID actual de su ArgoCD propietario,
server interno exacto, alias de conexión revisado, scope sin extras/duplicados,
y hashes de los demás campos data y metadata normalizada. Captura valores
públicos y hashes, nunca exporta el Secret. Repite la lectura después de SSA
y bloquea rotación/cambio durante el control. Tras un cambio autorizado de
conexión, inspeccionar un DRAFT nuevo y aprobar un perfil aparte; no reutilizar
reportes previos ni editar automáticamente expectativas para obtener PASS.


## Preflight único del cache dedicado

El controlador dedicado usa `controller.respectRBAC: normal`; el ConfigMap efectivo
debe declarar `resource.respectRBAC: normal`. Ambos se verifican contra el perfil
privado revisado. En Argo CD 3.5.3, `strict` puede conservar un tipo al detectar
permiso en un solo namespace y luego fallar al listar otro; `normal` descarta ese
tipo globalmente al recibir Forbidden. Por eso los permisos `list/watch` cubren la
unión finita de tipos namespaced deseados en **todos** los namespaces externos y
el propio controlador. Los permisos `get/update/patch` siguen limitados a nombres
y namespaces originales. No se añaden Secrets, HPA ni wildcards.
[Véase la implementación del cache 3.5.3](https://github.com/argoproj/argo-cd/blob/v3.5.3/gitops-engine/pkg/cache/cluster.go#L1039-L1090).

Después del bootstrap revisado y antes del primer sync:

```bash
python3 automation/scripts/check_cache_permissions.py \
  --render-dir /private/platform-render \
  --expected /private/expected-adoption.json \
  --report /private/cache-preflight-new.json --workers 2
```

Este control descubre los recursos del API y comprueba `can-i list`, `can-i watch`
y un LIST real con `limit=1` para cada par tipo/namespace, impersonando el SA y sus
grupos. Sólo guarda identidades, resultados y recuentos; nunca cuerpos ni nombres
de los elementos. También verifica los negativos y la estabilidad de la conexión
y tracking. Su PASS no acredita watches activos, readiness ni sync. Repetirlo si
cambia la matriz de acceso o configuración; no ejecutarlo dentro de cada SSA.
CSV/CRD siguen verificados por gates nativos del instructor; no se afirma que Argo
lea CSV en todos los namespaces ni que su salud reemplace esos gates.

En la revisión actual, la matriz finita cubre 14 namespaces: los 266 pares
tipo/namespace pasaron `can-i list/watch` y LIST real; también pasaron 34 negativos.
El bootstrap amplía sólo la lectura `list/watch` de esa unión finita, sin añadir
escrituras. Ese preflight por sí solo no acredita el handoff. La ejecución
posterior de las nueve fases y sus gates quedó registrada en
[VALIDATION.md](../VALIDATION.md).
