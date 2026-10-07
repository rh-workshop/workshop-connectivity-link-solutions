# Applications de plataforma

Generar las Applications con `automation/scripts/render_platform.py` después de
publicar el árbol Kustomize saneado. La fuente puede ser un repo HTTPS público
o el repo interno exacto
`http://cl-platform-git-repository.cl-platform-gitops.svc:8080/platform.git`
con `publication_mode: internal` en el perfil privado fuera de Git. Ambos requieren
un SHA real inmutable y la ruta publicada explícita; no se versionan URLs ficticias
como Applications instalables. Seguir la [secuencia de publicación y prueba del
ref remoto](../../scripts/README-adoption.md#secuencia-sin-sha-ficticio).
Los nombres son `cl-platform-<fase>` y la etiqueta
`app.kubernetes.io/part-of: connectivity-link`.

El renderer deja `automated` y finalizers ausentes. Cada recurso persistente lleva
`metadata.annotations.argocd.argoproj.io/sync-options: Prune=false,Delete=false`;
la Application usa `FailOnSharedResource=true`, `ServerSideApply=true` y
`ClientSideApplyMigration=false` (Argo CD 3.5.3). No se supone que opciones de
Application sustituyan la protección declarada en cada recurso. No crear una Application raíz que suponga que la salud de hijos
demuestra readiness de CSV/CRD. Seguir los gates del README Kustomize antes de
cada sync manual. El bootstrap de OpenShift GitOps permanece fuera de estas
Applications para evitar que el controlador adopte su propia instalación.

`access/project-and-rbac.yaml` se genera junto a las Applications para revisión
y bootstrap del instructor, fuera de las rutas reconciliadas por ellas. El
AppProject `cl-platform` permite sólo el repo elegido, namespaces finitos y tipos
proyectados. Excluye el namespace del servidor Git interno y recursos generados
CSV/CRD/InstallPlan. No concede acceso wildcard ni crea privilegios de auto-admin.

La identidad del controlador se toma exclusivamente de
`automation/common/platform-argocd.yml`; Applications y AppProject viven en
`cl-platform-argocd`. El namespace y la instancia se crean por bootstrap fuera
del árbol adoptado. Lab 6/default `openshift-gitops` permanece independiente.

Antes del primer sync, el instructor configura el cache de la conexión local
con `playbooks/platform-argocd.yml` y `platform_argocd_operation=configurar`
desde `automation/ansible`. El [contrato de scope](../../common/roles/platform_argocd/README.md#scope-de-la-conexión-local)
exige render revisado, targets explícitos (Namespace externos más la instancia),
UID del Secret y respaldo privado nuevo. Este paso evita `namespace not managed`;
no concede RBAC. No debe haber operaciones activas. Verificar la reconciliación
estable y capturar expectativas nuevas antes del gate SSA y del sync manual.

Escrituras namespaced y cluster-scoped (`get/update/patch`) sólo cubren nombres
inventariados no RBAC; `list/watch` permite cache de esos tipos. Todos los Roles,
Bindings y ClusterRoles originales son prerrequisitos externos con UID y contrato
canónico completo (`bootstrap/external-rbac.yaml`); no existe Application `rbac`.
El controlador no recibe permisos sobre el API group RBAC, create de recursos persistentes, delete, Secret,
bind ni escalate. Antes de SSA, el gate verifica los negativos de acceso con la identidad
y grupos reales. Un Role acotado no elimina permisos de otros bindings existentes.

El perfil completo con gateway-defaults e ingress tiene nueve fases. Regenerar
bundle, SHA y expectativas después de cambiar la identidad; los reportes del
controlador predeterminado no autorizan este handoff.

Los gates se ejecutan desde `automation/ansible` con
`ansible-playbook playbooks/platform-gate.yml -e platform_gate_phase=<fase> -e plataforma_gestor=argocd`
después del sync comprobado. El override es por gate; el bootstrap y perfil global
conservan Ansible hasta completar el handoff.
Reutilizan los roles existentes; no hay un motor Python de polling paralelo.
Authorino y el Deployment `kuadrant-console-plugin` son hijos del operador y no
forman parte del desired state de las Applications. Tracing se declara en el CR
Kuadrant; `runtime-actions.json` describe la excepción nativa explícita para el
env del plugin no expuesto por esa API. Verificar/aplicar ese workaround y repetir
el gate de observabilidad antes de laboratorios; no transferir el hijo a Argo CD.
El gate ingress-certificate valida TLS real sin cambiar la referencia;
ingress-reference sólo cambia el campo mediante el rol TLS con autorización y
backup externos explícitos.

Antes de cada sync, ejecutar el [gate SSA de adopción](../../scripts/README-adoption.md)
con expectativas privadas inspeccionadas. Rechaza deriva funcional, recursos nuevos
y permisos insuficientes como el ServiceAccount real. El renderer clasifica ACME,
resolvers CertManager y UWM como `external-preconditions.json`: verificar y preservar,
sin exportar Secrets ni declarar que GitOps los administra.

Los Namespaces también son prerrequisitos externos (`bootstrap/external-namespaces.yaml`),
fuera de desired state y del whitelist. El acceso sólo concede get de nombres finitos y
list/watch de namespaces. El gate verifica UID/Active/metadata/spec conservados, niega
patch/update en cada namespace y bloquea labels de managed-by o bindings admin hacia
el controlador dedicado. Se validan permisos directos, no aislamiento absoluto.

TempoMonolithic en modo OpenShift requiere sólo `create tokenreviews.authentication.k8s.io`
para su webhook. La regla efímera se genera condicionalmente fuera del bundle y no
incluye auth-delegator, SAR ni TokenRequest. El gate deniega estos dos últimos con
pruebas explícitas (34 negativos en el perfil de 13 namespaces).


El cache dedicado usa `respectRBAC: normal`. Los permisos de colección cubren
la unión finita de tipos namespaced deseados en cada namespace de la conexión,
incluido el propio; las escrituras conservan su alcance original por nombre.
Antes del primer sync, ejecutar el [preflight de permisos y LIST real](../../scripts/README-adoption.md#preflight-único-del-cache-dedicado).
No se conceden HPA ni Secrets para evitar errores de cache. CSV/CRD se validan
mediante los gates nativos independientes del instructor.
