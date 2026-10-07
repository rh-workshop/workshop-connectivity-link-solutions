"""Consulta Tempo y verifica spans observados; una consulta, sin polling ni secretos."""
import json
import ssl
import sys
import time
import urllib.error
import urllib.parse
import urllib.request


def attributes(items):
    return {item['key']: item.get('value', {}).get('stringValue')
            for item in items if isinstance(item, dict) and 'key' in item}


def policy_evidence(trace, request_id, started):
    """Exigir RID fresco y Check descendiente; no asumir cantidad de spans."""
    spans = {}
    for batch in trace.get('batches', trace.get('resourceSpans', [])):
        service = attributes(batch.get('resource', {}).get('attributes', [])).get('service.name')
        for scope in batch.get('scopeSpans', batch.get('instrumentationLibrarySpans', [])):
            for span in scope.get('spans', []):
                identity = span.get('spanId')
                if not identity or identity in spans:
                    return None
                spans[identity] = {**span, 'service': service,
                                   'attrs': attributes(span.get('attributes', []))}
    roots = {identity for identity, span in spans.items()
             if span['service'] == 'wasm-shim' and span.get('name') == 'kuadrant_filter'
             and span['attrs'].get('request_id') == request_id
             and int(span.get('startTimeUnixNano', 0)) >= int(started) * 1000000000}
    for identity, span in spans.items():
        if span['service'] != 'authorino' or span.get('name') != 'Check':
            continue
        ids = [span['attrs'][key] for key in ['authorino.request_id', 'guid:x-request-id']
               if key in span['attrs']]
        if not ids or any(value != request_id for value in ids):
            continue
        parent, visited = span.get('parentSpanId'), {identity}
        while parent in spans and parent not in visited:
            if parent in roots:
                return {'requestId': request_id, 'rootSpanId': parent,
                        'authorinoSpanId': identity, 'ancestryVerified': True}
            visited.add(parent)
            parent = spans[parent].get('parentSpanId')
    return None


def query(endpoint, started, service, request_id=None):
    sa = '/var/run/secrets/kubernetes.io/serviceaccount/'
    params = {'limit': '20', 'start': int(started), 'end': int(time.time())}
    if request_id:
        params['q'] = '{ resource.service.name = "wasm-shim" && span.request_id = ' + json.dumps(request_id) + ' }'
    else:
        params['tags'] = 'service.name=' + service
    context = ssl.create_default_context(cafile=sa + 'service-ca.crt')
    with open(sa + 'token') as token_file:
        headers = {'Authorization': 'Bearer ' + token_file.read().strip()}

    def fetch(url):
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers),
                                    context=context, timeout=15) as response:
            return json.load(response)

    try:
        result = fetch(endpoint + '?' + urllib.parse.urlencode(params))
        if request_id:
            evidence = None
            for metadata in result.get('traces', []):
                if int(metadata.get('startTimeUnixNano', 0)) < int(started) * 1000000000:
                    continue
                trace_id = metadata.get('traceID', '')
                if not trace_id or any(c not in '0123456789abcdef' for c in trace_id):
                    continue
                evidence = policy_evidence(fetch(endpoint.rsplit('/', 1)[0] + '/traces/' + trace_id), request_id, started)
                if evidence:
                    evidence['traceID'] = trace_id
                    break
            result = {'policyEvidence': evidence}
    except urllib.error.HTTPError as error:
        # No se vuelcan cabeceras, token ni cuerpos potencialmente sensibles.
        result = {'httpError': error.code, 'reason': str(error.reason)}
    print(json.dumps(result))


if __name__ == '__main__':
    query(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4] if len(sys.argv) > 4 else None)
