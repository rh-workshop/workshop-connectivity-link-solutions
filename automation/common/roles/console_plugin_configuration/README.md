# Configuración del plugin Kuadrant

La consola sólo carga `kuadrant-console-plugin` cuando aparece en
`Console.spec.plugins`. La verificación predeterminada exige ConsolePlugin,
backend Available/generación observada y habilitación exacta; Lab01 reutiliza
esta comprobación sin aplicar el workaround de métricas.

La habilitación es una precondición externa, fuera del desired state Argo CD.
Con el opt-in de escritura siguiente, el rol añade sólo el plugin ausente mediante
CAS de UID, resourceVersion y lista previa. Conserva otros plugins y rechaza
tracking/propiedad Argo CD; si ya está habilitado no escribe en Console.

`METRICS_WORKLOAD_SUFFIX=-istio` permite consultar workloads de OSSM/Istio.
La API padre no expone este ajuste en el perfil RHCL validado: este rol gestiona
una excepción operativa sobre el Deployment generado por `kuadrant-operator`.
Argo CD no debe incluir ese Deployment en su estado deseado; la plataforma no se
presenta como totalmente gestionada por GitOps mientras exista esta excepción.

Desde `automation/ansible/`, con configuración privada y kubeconfig del instructor:

```bash
# Solo verifica: falla de inmediato si falta el ajuste.
ansible-playbook playbooks/console-plugin.yml -e @/ruta/configuracion-privada.yml

# Workaround explícito, también permitido con gestor Argo CD.
ansible-playbook playbooks/console-plugin.yml -e @/ruta/configuracion-privada.yml \
  -e console_plugin_verificar_solo=false
```

El wrapper ejecuta primero las guardias de destino de `comun` (API y UID/infra/dominio
cuando se configuran). El rol exige el Deployment conocido, labels del operador y
ningún tracking, owner Application ni campos gestionados por Argo CD. Revalida
propiedad y existencia del contenedor inmediatamente antes de escribir.

El strategic merge modifica únicamente el env nombrado del contenedor existente;
conserva los demás env, contenedores, labels y configuración. Elimina un `valueFrom`
previo solo de ese env si necesita sustituirlo por el valor literal. Si ya coincide,
no escribe. Después espera generación observada, Available y valor efectivo.

Verifica nuevamente después de actualizaciones o reconciliaciones del operador:
el proveedor puede regenerar el Deployment. Lab 5 reutiliza este rol durante su
preparación Ansible. Tracing de Authorino procede de `Kuadrant.observability.tracing`;
no se parchea el hijo generado, y su `spec.tracing.endpoint` se verifica.
