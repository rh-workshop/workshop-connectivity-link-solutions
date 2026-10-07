"""Comprueba offline los contratos de espera DNS y mTLS de Lab11."""
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def load_yaml(path):
    return yaml.safe_load(path.read_text())


def check():
    common = load_yaml(ROOT / 'common/roles/comun/tasks/esperar_dns.yml')
    defaults = load_yaml(ROOT / 'common/roles/comun/defaults/main.yml')
    lab11 = load_yaml(ROOT / 'labs/lab11/roles/lab11/tasks/esperar_dns.yml')
    lab11_validar = load_yaml(ROOT / 'labs/lab11/roles/lab11/tasks/validar.yml')
    b2b_tasks = load_yaml(ROOT / 'labs/lab11/roles/lab11/tasks/probar_b2b.yml')
    fixture = load_yaml(ROOT / 'tests/fixtures/dns-wait.yml')

    auth_condition = common[0]['when']
    uri_task = common[1]['block'][0]
    uri = uri_task['ansible.builtin.uri']
    assert defaults['dns_verificar_autoritativos'] is True
    assert auth_condition == 'dns_verificar_autoritativos | default(true) | bool'
    assert uri['client_cert'] == '{{ dns_client_cert | default(omit) }}'
    assert uri['client_key'] == '{{ dns_client_key | default(omit) }}'
    assert 'until' in uri_task and uri_task['retries'] == '{{ dns_espera_local_reintentos | default(200) }}'
    assert uri_task['no_log'] == '{{ dns_client_cert is defined or dns_client_key is defined }}'
    assert common[1]['rescue'][0]['no_log'] == '{{ dns_client_cert is defined or dns_client_key is defined }}'

    calls = [task for task in lab11 if task.get('ansible.builtin.include_role', {}).get('tasks_from') == 'esperar_dns']
    assert len(calls) == 2
    soc_vars, b2b_vars = (task['vars'] for task in calls)
    assert 'dns_client_cert' not in soc_vars and 'dns_client_key' not in soc_vars
    assert b2b_vars['dns_client_cert'] == '{{ lab11_dir_local }}/socio-acme.crt'
    assert b2b_vars['dns_client_key'] == '{{ lab11_dir_local }}/socio-acme.key'
    assert not any('wk_dns_autoritativo' in task or 'ansible.builtin.uri' in task for task in lab11)

    tls_loop = next(task for task in lab11_validar if task.get('ansible.builtin.include_tasks') == 'probar_b2b.yml')
    actual_statuses = [case['b2b_esperado'] for case in tls_loop['loop']]
    assert actual_statuses == [case['expected_status'] for case in fixture['tls_cases']]
    failed_tls_assert = b2b_tasks[0]['block'][1]
    assert failed_tls_assert['when'] == 'b2b_esperado | int == -1'
    failed_tls_conditions = ' '.join(failed_tls_assert['ansible.builtin.assert']['that'])
    assert 'lab11_b2b.status == -1' in failed_tls_conditions
    assert 'TLSV' in failed_tls_conditions and 'ALERT' in failed_tls_conditions
    assert fixture['tls_cases'][-1]['expected_status'] == 200
    assert 'positive-control' in fixture['tls_cases'][-1]['name']

    for case in fixture['cases']:
        inputs = case['vars']
        actual_authoritative = bool(inputs.get('dns_verificar_autoritativos', defaults['dns_verificar_autoritativos']))
        actual_certificate = bool(inputs.get('dns_client_cert') and inputs.get('dns_client_key'))
        assert actual_authoritative is case['authoritative'], case['name']
        assert actual_certificate is case['client_certificate'], case['name']

    print(f"PASS Lab11 contracts: {len(fixture['cases'])} DNS cases and {len(fixture['tls_cases'])} mTLS cases")


if __name__ == '__main__':
    try:
        check()
    except (AssertionError, KeyError, OSError, yaml.YAMLError) as error:
        print(f'FAIL DNS wait contract: {error}', file=sys.stderr)
        sys.exit(1)
