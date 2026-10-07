# lab05 · Solución del laboratorio

Página: [lab5.adoc](https://rh-workshop.github.io/workshop-connectivity-link/lab5.html).
Contrato de rutas, dependencias, alcance y limpieza: entrada `lab05` de [catalog.yml](../../catalog.yml).

Observabilidad compartida: verificar por defecto; instalación solo por instructor.

Rol canónico: [`roles/lab05/`](roles/lab05/). Los manifiestos permanecen en sus plantillas; no se duplican aquí.

Desde `automation/ansible/`, con el destino y permisos verificados:

```bash
ansible-playbook playbooks/lab05.yml -e lab_id=user7
ansible-playbook playbooks/lab05.yml -e lab_id=user7 --tags validar
```

Validaciones: [`tasks/validar.yml`](roles/lab05/tasks/validar.yml).
La respuesta autenticada debe cumplir el contrato JSON publicado del banco.
Thanos identifica el workload real del Gateway y toma un contador antes del
tráfico: exige incremento de 200, 401 y 429, no series históricas. Requiere datos
ya scrapeados de ese workload; el instructor ejecuta este validador externo
con la ServiceAccount privada `validation-reader` y su acceso a Thanos.
No comparte su token ni concede `cluster-monitoring-view` a los participantes:
para *Observe → Metrics* basta el acceso `view` o `edit` a su propio proyecto,
seleccionado en la consola, con la consulta limitada a ese namespace.
Referencia: [métricas como desarrollador, OCP 4.22](https://docs.redhat.com/en/documentation/monitoring_stack_for_red_hat_openshift/4.22/html/accessing_metrics/accessing-metrics-as-a-developer).
El request-id devuelto en el 401 debe coincidir con su access log JSON.
Tempo debe devolver JSON con trazas del Gateway posteriores al inicio de la
prueba; no basta un contador de trazas antiguas. Además exige una traza fresca
wasm-shim/kuadrant_filter con el request-id devuelto y un span Authorino/Check
con ese identificador cuya ancestry alcanza el span raíz. No presupone siete
o doce spans. La ausencia por muestreo impide declarar comprobada esa señal;
repetir el recorrido según la página. La inspección de Limitador en peticiones
con cuota y la correlación con logs de componentes siguen siendo manuales.

Fixtures offline: `python3 automation/tests/contracts/lab05_signals.py` desde la raíz.
Grafana opcional (desactivado por defecto; actívalo con `lab05_grafana_instalar=true`): la verificación de plataforma comprueba los IDs publicados,
sincronización de la generación actual y contrato del datasource Thanos. Eso no
certifica datos en todos los paneles: las consultas upstream conservan las
limitaciones de etiquetas descritas en la página (App Developer, namespace y
request_url_path). El exportador `gatewayapi_*` es distinto del tráfico Istio;
los dashboards y sus resultados opcionales se inspeccionan por separado.
Fixtures de configuración: `python3 automation/tests/contracts/lab05_grafana.py`.
Limpieza selectiva: `ansible-playbook playbooks/limpieza.yml -e lab_id=user7 --tags limpieza_lab05`. Consulta `tasks/limpiar.yml`; conserva los prerrequisitos necesarios para los siguientes labs.
