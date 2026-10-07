# Postman · Connectivity Link

Importa [la colección](connectivity-link-workshop.postman_collection.json) y [el environment](connectivity-link-workshop.postman_environment.json). Selecciona **Connectivity Link · plantilla local**. Son 12 carpetas activas y 99 peticiones: Labs 3–12 (Labs 0–2 no requieren llamadas HTTP pues son configuración de cluster con `oc`), con 4A/4B separados y Bonus de IA.

## Configuración

Sustituye las URLs `example.com` por las de tu sesión, sin `/` final. `apiBaseUrl` es `https://$LAB_HOST`; `keycloakIssuer` incluye `/realms/$KEYCLOAK_REALM`. `cloudBaseUrl`, `sociosBaseUrl` y `b2bBaseUrl` corresponden a los Gateways de Labs 7 y 11. No uses el hostname interno del inventario: la petición pasa por `/inventario/items` del Gateway.

Carga contraseñas, claves y client secret **solo en los valores locales** del environment. Todos vienen vacíos y marcados como secretos. Las peticiones de token guardan `jwt`, `bobJwt`, `m2mReadJwt` y `m2mWriteJwt`; renueva el token correspondiente si caduca. `apiKey` es la clave registrada en Lab 4B, no una clave inventada. `migration*Key` son las claves de los planes del Lab 9. No compartas ni subas un environment exportado con valores reales.

## Ejecutar por laboratorio y fase

**No ejecutes toda la colección.** Los laboratorios cambian políticas: una misma URL puede responder 200, 401, 403, 429 o 500 según el paso. Primero aplica los manifiestos del laboratorio; después ejecuta su petición o subcarpeta. Cada descripción indica los requisitos y cada test comprueba el resultado esperado.

- Labs 0–2 no tienen peticiones HTTP: instalación y comprobaciones se hacen con `oc`.
- Lab 3 comprueba 404 antes de crear la ruta del Lab 4A.
- Labs 4A/4B prueban JWT, API keys, Party, Accounts y Audit. El cambio de rol, revocación y restauración se hacen fuera de Postman.
- Labs 5/6 llaman a Bank API; consola, logs, Git y reconciliación requieren los pasos del laboratorio. `requestId` guarda el ID de respuesta del Lab 5.
- Labs 7/8 prueban publicación cloud y servicio externo; las pruebas de inventario anteriores al rol preceden a la AuthPolicy que exige `inventario`.
- Labs 9/10 prueban migración, cuotas por plan, scopes M2M y canary.
- Lab 11 requiere tu IP autorizada y certificado cliente local para mTLS.
- Lab 12 solo llama servicios; **no detiene componentes**. Las peticiones 500 requieren la demo global explícita y sus pasos de restauración.
- Bonus envía el payload real del mock LLM y comprueba `usage.total_tokens`; la cantidad de respuestas 200 varía.

Para cuotas, espera **61 segundos**, renueva el JWT y ejecuta solo la subcarpeta una vez, sin llamadas paralelas ni pausa entre requests. Sus peticiones son finitas y comprueban la secuencia exacta. Gold no tiene límite. No hay bucles automáticos ni tolerancias que escondan errores.

## TLS y certificados

Conserva activa la verificación TLS. Para certificados privados, configura la CA correspondiente en **Settings → Certificates**. La configuración SelfSigned descrita en Lab 3 puede requerir corregir la cadena/certificado antes de que Postman lo acepte; esta colección no desactiva la verificación. Lab 7 debe funcionar con confianza pública. Para Lab 11, registra los archivos CRT/KEY de `socio-acme` localmente para el hostname B2B y puerto 443; no se incluyen en JSON. Sin certificado o con otra CA, el fallo ocurre antes de HTTP.

## Verificación del archivo

Desde la raíz del repositorio:

```bash
node postman/validate.cjs
```

Este control verifica JSON, variables, rutas canónicas, orden, scripts y secuencias de cuota sin enviar tráfico. La validación estructural no demuestra que el clúster ni los laboratorios estén funcionando. Formato: [Postman Collection v2.1](https://schema.postman.com/json/collection/v2.1.0/docs/index.html).
