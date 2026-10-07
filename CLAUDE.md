# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Solucionario **público** del workshop Red Hat Connectivity Link 1.4.3 sobre OpenShift 4.22: Ansible y OpenTofu que reproducen cada laboratorio, y la colección Postman. El contenido didáctico (fuente de verdad) vive en el repo privado `rh-workshop/workshop-connectivity-link`, publicado en https://rh-workshop.github.io/workshop-connectivity-link/. `AGENTS.md` es un enlace a este archivo.

## Dos repos hermanos

Clona ambos uno junto al otro; no se usan submódulos (el `npm run verify` del workshop rechaza `.gitmodules`):

```
rh-workshop/
├── workshop-connectivity-link/             sitio, páginas .adoc y tests del sitio (privado)
└── workshop-connectivity-link-solutions/   este repo (público)
```

Los chequeos que comparan con las páginas (`check_parity.py`, `catalog_parity.py`, `check_catalog.py`, `postman/validate.cjs`, el contrato del ServiceEntry del Lab 8) las localizan con `automation/scripts/workshop_pages.py`: `WORKSHOP_ROOT`, el clon hermano `../workshop-connectivity-link` o una carpeta superior con `antora.yml`. Sin workshop se **saltan con aviso**; una página nueva o cambiada exige ejecutarlos con el workshop presente.

Si cambia un YAML de una página del workshop, sincroniza su plantilla aquí (y viceversa) en el mismo trabajo.

## Comandos

```bash
# Comprobaciones locales, sin clúster (desde la raíz; PyYAML, Jinja2, ansible-core)
python3 automation/scripts/check_catalog.py
python3 automation/scripts/check_render.py
python3 automation/scripts/check_parity.py
python3 automation/tests/contracts/acme_issuer.py                    # un archivo de contratos
python3 automation/tests/contracts/acme_issuer.py AcmeIssuer.test_participant_scope_rejects_shared_and_other_names   # un caso
ls automation/tests/contracts/*.py | xargs -P 8 -n 1 python3         # todos, en paralelo
node postman/validate.cjs
python3 automation/scripts/validate_labs.py --labs lab04b,lab03      # planifica en orden de dependencias; --execute --values <yaml privado> ejecuta

# Contra el clúster (desde automation/ansible, con KUBECONFIG del clúster)
ansible-galaxy collection install -r requirements.yml
ansible-playbook playbooks/plataforma.yml            # verifica (o instala) la plataforma
ansible-playbook playbooks/lab09.yml -e lab_id=user7 # un lab con sus dependencias
ansible-playbook site.yml -e lab_id=user7            # prácticas incluidas; Lab00 privilegiado va aparte
ansible-playbook playbooks/limpieza.yml -e lab_id=user7 [--tags limpieza_lab11]
```

## Arquitectura

- **Roles canónicos, wrappers finos**: cada lab es un rol en `automation/labs/<lab>/roles/<lab>/`; lo compartido (tenant, realm Keycloak, ACME, plataforma, Argo CD) está en `automation/common/roles/`. `automation/ansible/ansible.cfg` los resuelve por `roles_path`, así que todo `ansible-playbook` se lanza **desde `automation/ansible/`**. Los `playbooks/labNN.yml` importan prerrequisitos y el rol; no duplican roles.
- **Lab nuevo**: rol en `automation/labs/<lab>/roles/`, su ruta en `roles_path`, wrapper en `playbooks/`, entrada en `automation/catalog.yml` (IDs, dependencias y `source_page`, que comprueba `check_catalog.py`) y el rol al final de `site.yml`.
- **Barrera de clúster**: `openshift_api_esperada` (en `automation/ansible/inventory/group_vars/all.yml`) hace fallar cualquier playbook si el kubeconfig apunta a otra API.
- **Aislamiento por participante**: todo lo que crea un rol lleva el sufijo de `lab_id` (`userXX`); los contratos verifican que el modo participante rechace nombres compartidos o de otro usuario.
- **Contratos frente a clúster**: `check_render.py` renderiza todas las plantillas con `automation/tests/fixtures/render-all.yml` y `StrictUndefined`, resolviendo como Ansible las variables que contienen Jinja (`resolve()`, p. ej. `letsencrypt-dns01-{{ lab_id }}`). `check_parity.py` compara las plantillas con los manifiestos de las páginas según `tests/fixtures/parity-*.yml`. Ninguno sustituye una ejecución real; la evidencia de clúster va en `automation/VALIDATION.md`.
- **Cobertura de paridad explícita**: toda plantilla está en un `parity-*.yml` o en `content-parity-exclusions.yml` con `reason` (preparación del instructor, credenciales que nunca se publican…). Al añadir o quitar plantillas, actualiza la clasificación y el recuento esperado de `catalog_parity.py`.

## Publicación

Repo público: nunca secretos, hostnames reales de clústeres o entornos RHPDS/OpenTLC, nombres de clientes ni Jira internos. Ejemplos con `example.com`/`example.invalid`, IPs de documentación (RFC 5737) y marcadores explícitos (`FIXTURE-NOT-A-KEY`, `NO_PUBLICAR`). Estado, `.tfvars` y credenciales reales quedan fuera de Git (ver `.gitignore`). Licencia Apache-2.0.

## Git

Commits en inglés, conventional commits, **una sola línea**, sin «Co-Authored-By».
