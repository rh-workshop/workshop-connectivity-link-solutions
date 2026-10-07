#!/bin/bash
# Operaciones Git del Lab 6 dentro del pod git-politicas: las mismas que el
# participante hace en su equipo (versionar la RateLimitPolicy resuelta, subir
# el límite por commit, revertir) y consultas de apoyo.
#   git-lab.sh publicar <limite> <mensaje> | revertir | limite | commit
set -euo pipefail
export HOME=/tmp
REPO="${GIT_RAIZ}/politicas.git"
TRABAJO=/srv/trabajo
FICHERO="${TRABAJO}/${GIT_RUTA}/ratelimitpolicy.yaml"
[ -d "${TRABAJO}/.git" ] || git clone -q "${REPO}" "${TRABAJO}" 2>/dev/null
cd "${TRABAJO}"
# Partir siempre del último commit publicado (alguien pudo empujar desde fuera).
git fetch -q origin 2>/dev/null || true
if git rev-parse -q --verify origin/main >/dev/null; then git reset -q --hard origin/main; fi
case "${1:-}" in
  publicar)
    mkdir -p "$(dirname "${FICHERO}")"
    # Mismo manifiesto que el heredoc del paso «Versionar la RateLimitPolicy».
    cat > "${FICHERO}" <<YAML
apiVersion: kuadrant.io/v1
kind: RateLimitPolicy
metadata:
  name: api-route-rl-${LAB_ID}
  namespace: ${NS_APP}
  labels:
    workshop.user: ${LAB_ID}
spec:
  targetRef:
    group: gateway.networking.k8s.io
    kind: HTTPRoute
    name: api-route-${LAB_ID}
  limits:
    "per-user-per-minute":
      rates:
        - limit: ${2}
          window: 60s
      counters:
        - expression: auth.identity.user_id
YAML
    git add -A
    if git diff --cached --quiet; then
      echo "SIN_CAMBIOS $(git rev-parse HEAD)"
      exit 0
    fi
    git commit -q -m "${3}"
    git push -q origin HEAD:main
    echo "PUBLICADO $(git rev-parse HEAD)"
    ;;
  revertir)
    git revert --no-edit HEAD >/dev/null
    git push -q origin HEAD:main
    echo "REVERTIDO $(git rev-parse HEAD)"
    ;;
  limite)
    sed -n 's/^ *- limit: \([0-9][0-9]*\)$/\1/p' "${FICHERO}" 2>/dev/null | head -1
    ;;
  commit)
    git rev-parse HEAD
    ;;
  *)
    echo "uso: git-lab.sh publicar <limite> <mensaje> | revertir | limite | commit" >&2
    exit 2
    ;;
esac
