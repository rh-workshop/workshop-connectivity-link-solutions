"""Localiza el repositorio del workshop, dueño de las páginas que comparan los chequeos de paridad."""
import os
from pathlib import Path

SOLUTIONS = Path(__file__).resolve().parents[2]
SKIP = ('Páginas del workshop no disponibles: monta este repositorio como submódulo del workshop '
        'o define WORKSHOP_ROOT con su ruta')


def workshop_root():
    """Devuelve la raíz del workshop (WORKSHOP_ROOT o la carpeta superior con antora.yml), o None."""
    configured = os.environ.get('WORKSHOP_ROOT')
    candidates = [Path(configured)] if configured else SOLUTIONS.parents
    for candidate in candidates:
        if (candidate / 'antora.yml').is_file() and (candidate / 'modules/ROOT/pages').is_dir():
            return candidate.resolve()
    return None
