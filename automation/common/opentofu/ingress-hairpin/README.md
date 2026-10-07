# Excepción HTTPS de hairpin NLB

El instalador/CCM mantiene el NLB del Service `openshift-ingress/router-default`.
Este componente OpenTofu **no crea ni importa** NLB, TG, listeners o targets:
`terraform_data` registra una excepción y llama a AWS para cambiar únicamente
`preserve_client_ip.enabled` en el TG del listener TCP 443. No activa Proxy Protocol.
El puerto 80 y los Gateway de participantes permanecen fuera del alcance.

Antes de planificar, el instructor revisa el CCM instalado y sus anotaciones,
las rutas compartidas, whitelist/rate limits, logs y configuración proxy de Keycloak.
Desactivar preservación cambia la IP observada por HAProxy/servicios HTTPS a la
del NLB; la revisión debe aceptar ese efecto. Las banderas del contrato registran
esa aprobación humana, **no reemplazan la evidencia**. No añadir la anotación CCM
de atributos: afecta todos los TG de este Service, incluido HTTP.

Crear un wrapper privado fuera de Git que referencie este módulo por ruta absoluta.
Configurar `reviewed_configuration` con cuenta, región, ARN NLB y TG actuales,
UID del Service, InfrastructureName y las dos aprobaciones; usar AWS_PROFILE,
KUBECONFIG y estado locales privados (0700, archivos 0600). Nunca descubrir y
adoptar automáticamente un ARN nuevo. El helper aborta si cambió la identidad,
la propiedad/tag, listener, Proxy Protocol o una anotación entra en conflicto.

Antes del plan, obtener un informe **solo lectura**, sin banderas de aprobación:
el JSON privado contiene identidad y `expected_current_preserve_client_ip=true`.

```bash
python3 /ruta/canonica/ingress-hairpin/configure.py --mode verify \
  --config /ruta/privada/review-input.json --report /ruta/privada/review.json
sha256sum /ruta/privada/review.json
```

Revisar el informe y fijar `approved_review_path`, `approved_review_sha256` y
`expected_current_preserve_client_ip` en el wrapper. El informe no aprueba el
cambio por sí mismo. El plan vincula también el hash del helper; cualquier
cambio del helper, configuración del NLB/TG HTTP, etiquetas, targets, listener
o baseline exige una nueva revisión. `terraform_data` **no detecta drift** al
refrescar estado: ejecutar siempre `verify` antes del plan y después del cambio.

```bash
tofu init
tofu plan -out=/ruta/privada/https.plan
# Revisar: solo terraform_data; ningún recurso AWS creado/importado/destruido.
tofu apply /ruta/privada/https.plan
```

`snapshot_path` es una ruta NUEVA en directorio 0700 fuera del repo. Antes de la
API se captura estado 0600; se vuelve a leer y se exige ausencia de drift.
Después se comprueba que ambos TG y listeners mantienen todo salvo el atributo.
El API AWS no ofrece CAS: existe una ventana residual entre lectura y escritura.

Para rollback, mantener los mismos ARN/UID, generar y revisar otro informe con
`expected_current_preserve_client_ip=false`, establecer `preserve_client_ip=true`
y otra `snapshot_path`, revisar un nuevo plan y aplicar. Se reemplaza solo el
marcador local, sin provisioner destroy ni eliminación AWS. No usar `tofu destroy`
como rollback. Si CCM recrea el TG, detenerse y revisar nuevos ARN/impacto;
la excepción no persiste automáticamente ni promete reconciliación continua.

Después de cualquier cambio: verificar ambas IP del NLB desde ambos nodos,
TLS/rutas compartidas y primer JWT en un realm nuevo. Estos comandos OpenTofu
no prueban funcionamiento del laboratorio. Documentación de AWS:
[hairpin y preservación IP](https://docs.aws.amazon.com/elasticloadbalancing/latest/network/load-balancer-troubleshooting.html).

Pruebas offline: `PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s automation/common/opentofu/ingress-hairpin/tests`.
