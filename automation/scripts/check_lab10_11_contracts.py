"""Comprueba offline los contratos exactos de cuotas y fallos TLS de Lab10/11."""
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]


def read(path):
    return yaml.safe_load(path.read_text())


def check():
    fixture = read(ROOT / 'tests/fixtures/lab10-11-validation.yml')
    lab10 = read(ROOT / 'labs/lab10/roles/lab10/tasks/techo.yml')
    cuota = read(ROOT / 'common/roles/comun/tasks/probar_cuota_exacta.yml')
    lab11 = read(ROOT / 'labs/lab11/roles/lab11/tasks/validar.yml')
    b2b = read(ROOT / 'labs/lab11/roles/lab11/tasks/probar_b2b.yml')

    lab10_block = next(task['block'] for task in lab10 if task.get('block'))
    quota_calls = [task for task in lab10_block if task.get('ansible.builtin.include_role', {}).get('tasks_from') == 'probar_cuota_exacta']
    assert len(quota_calls) == len(fixture['lab10_quota']['routes']) == 2
    for task, expected in zip(quota_calls, fixture['lab10_quota']['routes']):
        variables = task['vars']
        assert variables['cuota_limite'] == '{{ lab10_techo }}'
        assert variables['cuota_url'] == expected['url']
        assert variables['cuota_json_contract'] == expected['json_contract']
        assert variables['cuota_ventana_segundos'] == 60
        assert 'Authorization' in variables['cuota_cabeceras']

    quota_assert = next(task['ansible.builtin.assert'] for task in cuota if task.get('ansible.builtin.assert', {}).get('that') and 'cuota_exacta_codigos' in str(task['ansible.builtin.assert']['that']))
    exact_condition = ' '.join(quota_assert['that'])
    assert 'cuota_exacta_codigos' in exact_condition and '[200]' in exact_condition and '[429]' in exact_condition
    assert fixture['lab10_quota']['expected_statuses'] == [200, 200, 429]
    assert any(task.get('ansible.builtin.pause', {}).get('seconds') == '{{ cuota_ventana_segundos | default(60) | int + 1 }}' for task in cuota)

    tls_loop = next(task for task in lab11 if task.get('ansible.builtin.include_tasks') == 'probar_b2b.yml')
    statuses = [case['b2b_esperado'] for case in tls_loop['loop']]
    assert statuses == fixture['lab11_tls']['expected_statuses']
    tls_assert = b2b[0]['block'][1]['ansible.builtin.assert']
    tls_conditions = ' '.join(tls_assert['that'])
    assert 'lab11_b2b.status == -1' in tls_conditions
    assert 'TLSV' in tls_conditions and 'ALERT' in tls_conditions
    assert fixture['lab11_tls']['negative_status_requires_tls_alert'] is True
    assert statuses[-1] == fixture['lab11_tls']['positive_control_status'] == 200

    print('PASS Lab10/11 contracts: exact 200,200,429 on both routes; TLS alerts and valid-cert 200 control')


if __name__ == '__main__':
    try:
        check()
    except (AssertionError, KeyError, OSError, yaml.YAMLError) as error:
        print(f'FAIL Lab10/11 contract: {error}', file=sys.stderr)
        sys.exit(1)
