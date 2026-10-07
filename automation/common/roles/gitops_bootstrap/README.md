# Bootstrap de OpenShift GitOps

Este rol prepara el controlador que gestionará la plataforma. Por defecto solo
verifica su disponibilidad. No crea Applications ni sincroniza recursos RHCL.

## Ejecutar

Usa las colecciones de `automation/ansible/requirements.yml`, un kubeconfig con
permisos de instructor y configuración privada fuera de Git. Desde
`automation/ansible/`:

```bash
# Comprueba sintaxis; no consulta el clúster.
ansible-playbook --syntax-check playbooks/gitops-bootstrap.yml

# Verifica el operador y Argo CD existentes.
ansible-playbook playbooks/gitops-bootstrap.yml -e @/ruta/configuracion-privada.yml

# Instala únicamente los recursos de bootstrap ausentes.
ansible-playbook playbooks/gitops-bootstrap.yml -e @/ruta/configuracion-privada.yml \
  -e gitops_bootstrap_verificar_solo=false
```

La configuración privada debe indicar `openshift_api_esperada`. Puede reforzar
el destino con `openshift_cluster_uid_esperado` (UID de `kube-system`),
`openshift_infra_name_esperado` y `openshift_console_domain_esperado`. No incluyas
credenciales ni valores reales del entorno en el repositorio.

## Propiedad y comprobaciones

`gitops_bootstrap_verificar_solo` vale `true` por defecto. Instalar este
controlador es una excepción explícita permitida con `plataforma_gestor=argocd`;
los instaladores de plataforma y observabilidad continúan bloqueados en ese modo.

El rol busca Subscriptions GitOps en todo el clúster, conserva el namespace de
una instalación existente y rechaza duplicados. Si falta el operador, conserva
un OperatorGroup global existente y crea uno solo cuando no hay ninguno; rechaza
alcances incompatibles. No cambia canales ni configuración existentes.

Finalmente espera CSV `Succeeded`, CRD ArgoCD `Established` y la instancia
Argo CD `Available`. Los nombres y canal son configurables mediante
`gitops_bootstrap_operador`, `gitops_bootstrap_argocd_namespace` y
`gitops_bootstrap_argocd_instancia`; sus defaults conservan el perfil de Lab 6.
