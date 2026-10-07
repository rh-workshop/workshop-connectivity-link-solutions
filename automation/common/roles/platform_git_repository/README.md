# Fuente Git interna de validación

Este rol permite probar Argo CD con una fuente privada interna. `verificar` es
el modo por defecto; no instala ni publica. La publicación usa los permisos
`pods/exec` del instructor autenticado mediante `oc`; no se crean RoleBindings,
credenciales ni endpoints de push. No concedas esos permisos a participantes.

Desde `automation/ansible`, ejecutar `ansible-playbook
playbooks/platform-git-repository.yml -e platform_git_repository_operation=instalar`
crea PVC, Deployment y Service. El wrapper ejecuta primero los guards de
identidad del rol `comun`. Para transferir, exporta `KUBECONFIG` explícitamente;
el helper compara la API efectiva de `oc` con la del cliente Ansible antes de exec. OpenShift asigna UID y fsGroup mediante su SCC;
no se fija root ni un grupo propio. Debe existir una StorageClass compatible.

Genera una instantánea con el Python que tiene PyYAML instalado:

```bash
python3 ../common/roles/platform_git_repository/files/repository.py bundle \
  --source /ruta/privada/fuente-renderizada --path /ruta/privada/platform.bundle
ansible-playbook playbooks/platform-git-repository.yml \
  -e platform_git_repository_operation=publicar \
  -e platform_git_repository_bundle=/ruta/privada/platform.bundle
```

Las rutas son ejemplos. Fuente y bundle deben estar fuera de cualquier checkout.
La fuente admite sólo YAML/JSON Kubernetes o Kustomization: rechaza Secrets,
secretGenerator, plugins generators, patrones conocidos de credenciales y symlinks.
No es un detector completo de secretos: el instructor debe revisar los valores
ante cualquier publicación. No incluir informes ni archivos opacos. No se
imprime contenido privado. La publicación reemplaza `main` por la instantánea
validada; cada SHA conserva una referencia `refs/tags/releases/<sha>` para rollback.
Argo CD debe usar un SHA exacto, con sincronización manual. No borrar releases
activas ni ejecutar GC sin revisar las Applications.

RepoURL: `http://cl-platform-git-repository.cl-platform-gitops.svc:8080/platform.git`.
Sólo pods `cl-platform-repo-server` en `cl-platform-argocd` pueden acceder por
NetworkPolicy; el propio pod puede usar loopback. HTTP rechaza receive-pack;
POST upload-pack es necesario para lectura Git smart HTTP.
La identidad se lee de `common/platform-argocd.yml`. Una NetworkPolicy anterior
sin propiedad declarada requiere revisión y adopción explícita antes de actualizarla.

Usa las operaciones `backup` y `restaurar` con una ruta privada de bundle.
Backup incluye todas las releases y no sobrescribe archivos; conserva la copia fuera del clúster y protege
sus permisos. PVC resiste recreación del pod, pero no sustituye recuperación
ante pérdida del clúster. Para producción, usa un servicio Git privado externo
con autenticación, TLS y copias administradas.
