# Acceso de validación a monitorización

El wrapper `playbooks/validation-access.yml` ejecuta los guards de identidad de
`comun`. Por defecto verifica el acceso existente sin escribir. Para crearlo,
el instructor ejecuta desde `automation/ansible`:

```bash
ansible-playbook playbooks/validation-access.yml \
  -e validation_access_verificar_solo=false
```

Sólo gestiona `validation-reader` en `wk_ns_app` y su ClusterRoleBinding
`cl-validation-reader-<lab_id>` al rol existente `cluster-monitoring-view`.
El rol permite leer monitorización del clúster; no limita métricas al namespace
participante. No crea otros permisos ni adopta identidades o vínculos ajenos.

No solicita tokens, crea Secrets ni guarda credenciales. El instructor debe
solicitar un TokenRequest de duración limitada y entregarlo únicamente al
proceso de validación privado; nunca a stdout, archivos del repositorio o Git.
La ServiceAccount tiene el montaje automático del token desactivado.
