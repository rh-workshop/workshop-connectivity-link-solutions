# Instancia Argo CD de plataforma

Este rol crea una instancia aislada del controlador usado en Lab 6. La identidad
procede exclusivamente de `automation/common/platform-argocd.yml`, expuesta por
`comun` como `wk_platform_argocd`. No instala el operador compartido: reutiliza
su verificación canónica y exige el CRD servido `argoproj.io/v1beta1` con los
campos de aislamiento antes de escribir.

Desde `automation/ansible`, usando un perfil privado fuera de Git con
`openshift_api_esperada` y `openshift_cluster_uid_esperado` inspeccionados:

```bash
ansible-playbook playbooks/platform-argocd.yml -e @/private/values.yml
ansible-playbook playbooks/platform-argocd.yml -e @/private/values.yml -e platform_argocd_operation=instalar
```

`verificar` es el modo predeterminado: sólo consultas y comprobaciones, sin
aplicar recursos. `instalar` es explícito y rechaza namespaces o instancias
existentes sin las etiquetas de propiedad exactas, en borrado o con aislamiento
distinto. `configurar` modifica sólo el scope de una conexión existente, según
el contrato de la sección siguiente. La instalación escribe únicamente el Namespace y el CR ArgoCD; el
operador reconcilia sus componentes.

El CR declara `defaultClusterScopedRoleDisabled: true`,
`controller.respectRBAC: normal` y `extraConfig.application.resourceTrackingMethod:
annotation`. No etiqueta el namespace con `managed-by`, no modifica
`ARGOCD_CLUSTER_CONFIG_NAMESPACES`, la instancia predeterminada ni configuración
global. Se comprueban Available, el ServiceAccount esperado y el ConfigMap local
de tracking. No se crean tokens, Secrets, Applications ni permisos de plataforma.

El bootstrap RBAC acotado y la [prueba de adopción](../../../scripts/README-adoption.md)
son pasos separados del instructor. Una instancia Available no demuestra acceso
a recursos de plataforma ni reconciliación real. No ejecutar sync antes de esos
gates. No hay limpieza automática de esta instancia persistente.

## Scope de la conexión local

`platform_argocd_operation=configurar_controlador` permite la transición explícita
del CR owned de `strict` a `normal`. Requiere una ruta privada nueva en
`platform_argocd_controller_backup_path`, respalda sólo UID/versión y el campo
anterior y aplica CAS exclusivamente a `spec.controller.respectRBAC`. Rechaza
operaciones Application activas y espera `resource.respectRBAC=normal` en el
ConfigMap generado por el operador; nunca modifica ese ConfigMap directamente.
Argo CD 3.5.3 inicializa este modo al arrancar: tras cambiarlo, el rol renueva
únicamente el StatefulSet del controlador dedicado, comprobando propietario,
UID, cuenta de servicio, pods nuevos Ready y revisión estable. El operador puede
revertir la anotación temporal del template; una revisión nueva permanente no
es obligatoria. La prueba exige UID de pods nuevos y hash igual a la revisión
actual del StatefulSet, sin sustituir el UID del StatefulSet. No borra pods ni cambia
réplicas. Si el CR ya está en normal pero el proceso conserva el modo anterior,
`platform_argocd_controller_restart=true` autoriza esa misma renovación acotada:

```bash
ansible-playbook playbooks/platform-argocd.yml -e @/private/values.yml \
  -e platform_argocd_operation=configurar_controlador \
  -e platform_argocd_controller_backup_path=/private/controller-backup-new.json \
  -e platform_argocd_controller_restart=true
```

Operaciones Application terminadas no bloquean el cambio; operaciones pendientes,
Running o Terminating sí. Mantener la ventana sin sync concurrente durante
planificación, CAS y renovación.
`verificar` exige normal. El modo no concede permisos: el bootstrap separado
mantiene una unión finita de tipos para `list/watch` en los namespaces revisados,
sin lecturas Secret ni escrituras adicionales. La unión de namespaces de la
conexión local sigue verificándose sin modificarla en esta transición.

`platform_argocd_operation=configurar` amplía únicamente el cache de la conexión
local existente, sin conceder RBAC. Requiere un render privado revisado en
`platform_argocd_render_dir`, `platform_argocd_target_namespaces` explícitos que
coincidan exactamente con los Namespace de `external-preconditions.json` más
el namespace de la instancia, el UID observado en
`platform_argocd_cluster_secret_uid_esperado` y una ruta privada nueva en
`platform_argocd_scope_backup_path`.

No debe haber operaciones Application pendientes, Running ni Terminating.
El rol rechaza conexiones locales duplicadas, un server distinto de
`https://kubernetes.default.svc` o propiedad ArgoCD ajena. Guarda exclusivamente
UID/versión e información anterior de `namespaces`/`clusterResources` con modo
0600, fuera de Git, sin symlinks ni sobrescritura. No exporta `config`, tokens
ni certificados. El patch parcial comprueba UID, resourceVersion y los campos
anteriores, sin sustituir el Secret completo. Un conflicto requiere releer y
revisar; no reintentar con un snapshot viejo ni restaurar un Secret completo.

Tras el patch espera 60 segundos, verifica la unión exacta sin duplicados
(el orden es irrelevante), `clusterResources=true`, y un hash en memoria idéntico
de los demás campos de datos. No modifica labels `managed-by` ni variables
globales del operador y no inicia sync. `verificar` con los mismos targets/render
comprueba el scope sin escribir recursos ni respaldo. El instructor debe mantener
la ventana sin sync concurrente; estas lecturas no bloquean operaciones futuras.

Contrato de referencia: [instancias Argo CD en OpenShift GitOps 1.22](https://docs.redhat.com/en/documentation/red_hat_openshift_gitops/1.22/html-single/argo_cd_instance/index).
