# Defaults compartidos de la clase Istio

`templates/configmap.yaml.j2` es la fuente canónica. Crea en el namespace del
plano de control un ConfigMap etiquetado
`gateway.istio.io/defaults-for-class: istio`. Su clave `service` contiene solo
un patch de `metadata.annotations`; no define `spec.type`, para conservar los
Gateways ClusterIP de diagnóstico del Lab 12.

Versiones verificadas del formato: Istio 1.30.4 y 1.30.5. El rol exige CR `Istio`
Ready, versión admitida y `spec.namespace` coincidente; rechaza un
`meshConfig.rootNamespace` diferente en este perfil. Fuente del controlador:
[Istio 1.30.5](https://github.com/istio/istio/blob/1.30.5/pilot/pkg/config/kube/gatewaycommon/deploymentcontroller.go).

Desde `automation/ansible/`, verificar es el modo predeterminado:

```bash
ansible-playbook playbooks/gateway-defaults.yml --extra-vars @/ruta/privada/valores.yml
```

Instalar requiere `gateway_defaults_verificar_solo=false` y
`plataforma_gestor=ansible`. Los valores privados contienen la selección
`aws_load_balancer_subnet_ids`, nunca IDs reales en Git. El rol rechaza Gateways
Istio ajenos (identidad del usuario y namespace), defaults duplicados y ConfigMaps
sin propiedad del taller o gestionados por operadores. Los marcadores Argo CD
solo se admiten en modo verificar con `plataforma_gestor=argocd`; nunca habilitan
escrituras Ansible. El alcance es toda
la clase Istio; no ejecutar como participante sobre una plataforma compartida.

`gateway_defaults_backup=true` guarda antes de aplicar el ConfigMap anterior
(lista vacía si no existía) y el inventario de Gateways, en una carpeta nueva
privada fuera de Git. No se borran backups anteriores. Este rol no modifica
Gateways existentes ni elimina anotaciones explícitas: la migración del entorno
es una operación independiente del instructor.
