#!/usr/bin/python
"""Una muestra HTTP finita concurrente; sin reintentos ni motor de polling."""
import concurrent.futures
import json
import time
import requests


def workload(url, headers, count, parallelism, budget, clock=time.monotonic, fetch=requests.get):
    started = clock()
    deadline = started + budget

    def request(_):
        remaining = deadline - clock()
        if remaining <= 0:
            return {'status': -1, 'error': 'deadline'}
        try:
            with fetch(url, headers=headers, verify=False, allow_redirects=False,
                       timeout=(min(3, remaining), min(3, remaining)), stream=True) as response:
                body = bytearray()
                for chunk in response.iter_content(chunk_size=8192):
                    body.extend(chunk)
                    if clock() >= deadline or len(body) > 1048576:
                        return {'status': -1, 'error': 'deadline-or-body-limit'}
                result = {'status': response.status_code,
                          'content_type': response.headers.get('Content-Type', '')}
                try:
                    result['json'] = json.loads(body)
                except (ValueError, UnicodeDecodeError):
                    pass
                return result
        except requests.RequestException as error:
            return {'status': -1, 'error': type(error).__name__}

    with concurrent.futures.ThreadPoolExecutor(max_workers=parallelism) as executor:
        results = list(executor.map(request, range(count)))
    return {'results': results, 'duration': clock() - started}


def main():
    from ansible.module_utils.basic import AnsibleModule
    module = AnsibleModule(argument_spec={
        'url': {'type': 'str', 'required': True},
        'headers': {'type': 'dict', 'default': {}, 'no_log': True},
        'count': {'type': 'int', 'default': 300},
        'parallelism': {'type': 'int', 'default': 20},
        'budget': {'type': 'int', 'default': 45},
    }, supports_check_mode=False)
    params = module.params
    if not params['url'].startswith('https://') or not 1 <= params['count'] <= 300 or not 1 <= params['parallelism'] <= 20 or not 1 <= params['budget'] <= 45:
        module.fail_json(msg='Muestra HTTPS fuera de los límites permitidos.', invocation={})
    result = workload(**{key: params[key] for key in ['url', 'headers', 'count', 'parallelism', 'budget']})
    module.exit_json(changed=False, invocation={}, **result)


if __name__ == '__main__':
    main()
