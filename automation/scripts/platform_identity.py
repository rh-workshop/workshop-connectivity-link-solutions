"""Identidad de plataforma única compartida con los roles Ansible."""
from pathlib import Path
import re
import yaml

SOURCE = Path(__file__).resolve().parents[1] / 'common/platform-argocd.yml'


def load_identity():
    data = yaml.safe_load(SOURCE.read_text())
    keys = {'namespace', 'name', 'service_account', 'repo_server_label', 'repo_server_container'}
    if not isinstance(data, dict) or set(data) != keys or any(
            not isinstance(value, str) or not re.fullmatch(r'[a-z0-9](?:[a-z0-9-]*[a-z0-9])?', value)
            or len(value) > 63 for value in data.values()):
        raise ValueError('invalid_canonical_platform_identity')
    if data['namespace'] == 'openshift-gitops':
        raise ValueError('default_workshop_controller_not_platform_identity')
    return data
