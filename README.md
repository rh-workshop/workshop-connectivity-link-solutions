# Solucionario · Workshop Red Hat Connectivity Link

Soluciones automatizadas de los laboratorios del taller **Red Hat Connectivity Link 1.4.3** sobre **OpenShift 4.22**.
El taller (teoría y laboratorios paso a paso) está en https://rh-workshop.github.io/workshop-connectivity-link/

| Carpeta | Contenido |
|---|---|
| [`automation/`](automation/README.md) | Ansible por laboratorio, roles comunes, plataforma GitOps y OpenTofu para la infraestructura AWS externa. Deja a un participante al final de cualquier laboratorio o prepara el clúster del taller |
| [`postman/`](postman/README.md) | Colección y entorno Postman para llamar a las APIs de los laboratorios |

## Uso rápido

```bash
cd automation/ansible
ansible-galaxy collection install -r requirements.yml
ansible-playbook playbooks/lab04b.yml -e lab_id=user7
```

Requisitos, variables y la secuencia completa: [`automation/README.md`](automation/README.md).

## Comprobaciones locales (sin clúster)

```bash
python3 automation/scripts/check_catalog.py
python3 automation/scripts/check_render.py
python3 automation/tests/contracts/render_contract.py
node postman/validate.cjs
```

Los chequeos que comparan las plantillas y la colección con las páginas del taller (`check_parity.py`, `catalog_parity.py`, `postman/validate.cjs`) necesitan el repositorio del workshop. Lo encuentran solo si está clonado junto a este (`../workshop-connectivity-link`) o con `WORKSHOP_ROOT` apuntando a él; si no, se saltan con un aviso.

## Licencia

[Apache-2.0](LICENSE).
