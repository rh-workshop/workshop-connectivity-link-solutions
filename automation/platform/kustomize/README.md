# Plataforma declarativa por fases

Las plantillas de los roles comunes (`plataforma`, `gateway_defaults`, ACME)
y Lab05 siguen siendo la única fuente de sus manifiestos. `components/*/component.yml` describe la
proyección; no contiene otra copia de esos recursos. El renderer genera un árbol
Kustomize independiente, un mapa de identidades y hashes de las fuentes.

```bash
python3 automation/scripts/render_platform.py --output build/platform-gitops
kustomize build build/platform-gitops/overlays/example
python3 automation/tests/contracts/platform_gitops.py
```

La salida nueva evita sobrescribir artefactos revisados. El overlay de ejemplo
usa `apps.cluster.example.com`; no representa un entorno listo para desplegar.
Una zona pública real requiere `public_hosts` explícito. No se aceptan variables
de contraseñas, tokens, endpoints privados ni Secrets en los artefactos. Crear
los Secrets de Keycloak fuera de Git antes de sincronizar su fase; el gate
`keycloak-prerequisites` comprueba sus claves sin mostrar sus valores.
`required-secrets.json` enumera únicamente nombres y claves de todos los Secrets
excluidos, incluido el token de datasource Grafana; prepararlos por el mecanismo
de secretos del entorno, sin publicar sus valores.

## Publicación y adopción

Argo CD necesita los **artefactos generados versionados en un repositorio remoto**;
no puede leer `build/` de la máquina de control. Revisar el YAML, publicar solo el
árbol saneado y conservar su SHA. Generar Applications con `--repo-url`,
`--revision <SHA de 40 caracteres>` y `--published-path <ruta del árbol publicado>`.
No se presupone que esa ruta exista hasta publicar y comprobar su revisión.

Comparar `adoption-map.json` con el inventario real antes de cada sync. El campo
`adoption_map` puede conservar nombres existentes de Subscription/OperatorGroup
(clave `apiVersion|kind|namespace|name`); no crear un segundo OperatorGroup.
No se adoptan Namespaces ni recursos RBAC existentes: son prerrequisitos externos.
Tampoco CSV, CRD, InstallPlan ni Services/Deployments de los Gateways generados
por operadores. Usar la [entrada operativa única](../../scripts/README-adoption.md#entrada-operativa)
para preparar, publicar, comprobar SSA y solicitar el sync manual.

Un diff de adopción debe conservar íntegros los specs existentes de Istio,
Kuadrant y Keycloak, incluidos tracing, portal y almacenamiento. Un renderer base
no demuestra esa paridad con el clúster. `handoff-blockers.json` bloquea la entrega
de propiedad mientras falte la imagen KSM real. Authorino y el Deployment del
plugin conservan dueño operador y están excluidos del árbol deseado. No habilitar
reconciliación automática ni sincronizar un spec parcial sobre un objeto existente.

## Excepción del plugin y tracing propagado

El CR Kuadrant contiene `spec.observability.tracing.defaultEndpoint`; su operador
propaga ese endpoint al Authorino generado. No proyectar ni parchear el hijo.
El gate `observability` comprueba que el endpoint del hijo coincide con el padre.

La API padre no expone `METRICS_WORKLOAD_SUFFIX` del plugin. `runtime-actions.json`
registra el workaround nativo `console_plugin_configuration`, cuya verificación
no escribe y cuya aplicación exige `console_plugin_verificar_solo=false`.
El rol comprueba propiedad operador y ausencia de tracking Argo, y modifica sólo
ese env por strategic merge; no crea ni adopta el Deployment. Esta excepción
documentada admite gestor Argo porque ninguna Application gestiona ese hijo.

Después del sync de Kuadrant/observabilidad, verificar el plugin con el perfil
privado; si el sufijo difiere, aplicar explícitamente el workaround y repetir el
gate completo `observability` antes de laboratorios. Una reconciliación o upgrade
del operador puede requerir repetirlo; Argo no corrige ese env por sí solo.

```bash
cd automation/ansible
ansible-playbook playbooks/console-plugin.yml -e @/ruta/privada/platform-values.yml
ansible-playbook playbooks/console-plugin.yml -e console_plugin_verificar_solo=false \
  -e @/ruta/privada/platform-values.yml
ansible-playbook playbooks/platform-gate.yml -e platform_gate_phase=observability \
  -e @/ruta/privada/platform-values.yml
```

## Orden con gates explícitos

Sincronizar manualmente una fase y ejecutar su gate antes de avanzar:
`operators` → `istio-cni` → `istio` → `kuadrant` → `cert-manager` →
`keycloak-prerequisites` (gate previo, no Application) → `keycloak` →
`observability`. Cuando corresponda, insertar `gateway-defaults` después de
`istio` y añadir `ingress-certificate` al final: siete fases base, nueve con
ambos componentes. RBAC y Namespaces son prerrequisitos externos, no fases
reconciliadas. Ejemplo de consulta, sin escrituras:

```bash
cd automation/ansible
ansible-playbook playbooks/platform-gate.yml -e platform_gate_phase=operators \
  -e @/ruta/privada/platform-values.yml -e plataforma_gestor=argocd
```

El gate OLM exige `installedCSV`, CSV `Succeeded` y CRD `Established`; una
Subscription saludable o una wave no los sustituye. Los CRs necesitan Ready,
GatewayClass Accepted y generación observada cuando la API la informa. Las
Applications empiezan sin auto-sync ni finalizer, con `FailOnSharedResource=true`.
La protección de prune/delete está en la anotación sync-options de **cada
recurso persistente**, no sólo en opciones de la Application. No se usa Force
ni Replace. Revisar `access/project-and-rbac.yaml` y comprobar los permisos
efectivos del controlador antes de adoptar objetos con el AppProject `cl-platform`.
Detener escrituras Ansible de plataforma al transferir su propietario a Argo CD;
los laboratorios siguen gestionando únicamente sus recursos de participante.

## Defaults AWS compartidos (opt-in)

`aws_load_balancer_subnet_ids: []` conserva las siete fases base. Una lista
no vacía de IDs existentes activa `gateway-defaults` inmediatamente después de
`istio` y antes de cualquier laboratorio. Proyecta la plantilla canónica del rol
`gateway_defaults` al namespace `Istio.spec.namespace`; su ConfigMap se etiqueta
para GatewayClass `istio` y contiene sólo un patch de anotaciones del Service.
No cambia `spec.type`, por lo que conserva el ejercicio ClusterIP del Lab12.

Ejecutar el gate `gateway-defaults` con el mismo perfil privado después del sync.
Comprueba defaults únicos y alcance de los Gateways mediante el rol compartido;
no instala recursos. Revisar inventario y propiedad antes de activar una opción
que afecta toda la clase. Los Gateways heredan subnets por defecto
(`aws_gateway_subnets_override: false`); Lab11 conserva PROXY protocol y su
parametersRef. Los overrides de participante requieren opción explícita.
Los IDs y dominios reales de runtime siguen la frontera del bundle interno;
no publicar ese perfil ni su árbol en Git público.

## Certificado del ingress del clúster (opt-in)

`ingress_certificate_enabled` es false por defecto. Para activarlo, proporcionar
`ingress_domain` exactamente como `Ingress.config/cluster.spec.domain` detectado
fuera del renderer; no añade `apps.`. También exige `acme_dns_zone`,
`acme_route53_hosted_zone_id` y `acme_route53_region`. Se proyecta un Issuer
namespaced desde la fuente canónica ACME y un Certificate `cl-ingress-tls` en
`openshift-ingress`, con SAN del dominio y wildcard. El Secret AWS se prepara
fuera de Git en ese namespace; nunca se incluye la clave privada ni el Secret TLS.

La fase Certificate no toca IngressController: `platform_gate_phase=ingress-certificate`
usa `ingress_certificate_mode=verify` con comprobación del servicio desactivada,
para verificar el certificado emitido antes de cambiar la referencia. El rol
canónico verifica dominio real, Certificate Ready, SAN, vigencia, keymatch y
confianza criptográfica; no hay flag que sustituya esa validación.

La segunda fase es una transición explícita, no una consulta de readiness:

```bash
cd automation/ansible
ansible-playbook playbooks/platform-gate.yml \
  -e platform_gate_phase=ingress-reference \
  -e platform_gate_allow_reference_change=true \
  -e ingress_certificate_transicion=true \
  -e ingress_certificate_backup=/ruta/privada/ingress-backup.json \
  -e @/ruta/privada/platform-values.yml
```

Sólo el rol TLS aplica `defaultCertificate`, después de validar el material y
guardar el backup externo. Espera recuperación de operadores y verifica el
certificado realmente servido; la reversión usa su modo `rollback`. Ningún
manifest de IngressController parcial aparece en Kustomize. Todos los demás gates
son consultas nativas Ansible: identidad común, CSV instalado y CRDs Established,
readiness/generación, permisos existentes y verificación completa Lab05.

## Bundle interno de runtime

`publication_mode: internal` permite nombres de dominio no publicables sólo con
`--repo-url http://cl-platform-git-repository.cl-platform-gitops.svc:8080/platform.git`.
Ese árbol debe permanecer fuera de cualquier checkout y publicarse únicamente
en ese servidor interno de lectura; nunca subirlo a Git público. El modo público
conserva la revisión de `public_hosts`. Ambos modos excluyen Secrets y credenciales.
