'use strict';
// Comprueba el contrato del archivo sin conexiones HTTP ni credenciales.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const directory = __dirname;
// Las páginas viven en el workshop: WORKSHOP_ROOT o la carpeta superior con antora.yml (submódulo).
const workshopRoot = (() => {
  const candidates = process.env.WORKSHOP_ROOT ? [path.resolve(process.env.WORKSHOP_ROOT)] : [];
  for (let dir = path.resolve(directory, '..', '..'); !process.env.WORKSHOP_ROOT; dir = path.dirname(dir)) { candidates.push(dir); if (dir === path.dirname(dir)) break; }
  return candidates.find(dir => fs.existsSync(path.join(dir, 'antora.yml')) && fs.existsSync(path.join(dir, 'modules/ROOT/pages')));
})();
const collection = JSON.parse(fs.readFileSync(path.join(directory, 'connectivity-link-workshop.postman_collection.json')));
const environment = JSON.parse(fs.readFileSync(path.join(directory, 'connectivity-link-workshop.postman_environment.json')));
assert.equal(collection.info.schema, 'https://schema.getpostman.com/json/collection/v2.1.0/collection.json');
const expectedFolders = ['Lab 3', 'Lab 4A', 'Lab 4B', 'Lab 5', 'Lab 6', 'Lab 7', 'Lab 8', 'Lab 9', 'Lab 10', 'Lab 11', 'Lab 12', 'Bonus'];
assert.deepEqual(collection.item.map(folder => folder.name.split(' · ')[0]), expectedFolders);
const variables = new Map(environment.values.map(value => [value.key, value]));
assert.equal(variables.size, environment.values.length, 'No duplicar variables');
for (const value of variables.values()) {
  if (/(password|jwt|key|secret)$/i.test(value.key)) {
    assert.equal(value.type, 'secret', value.key);
    assert.equal(value.value, '', 'Plantilla sin secretos: ' + value.key);
  }
}
for (const [, name] of JSON.stringify(collection).matchAll(/\{\{([A-Za-z][A-Za-z0-9]*)\}\}/g)) assert(variables.has(name), 'Variable desconocida: ' + name);
const canonicalPaths = new Map([
  ['/api/v1/party', 'lab4.adoc'], ['/api/v1/accounts', 'lab9-migracion-3scale.adoc'],
  ['/admin/audit-log', 'lab4-api-key.adoc'], ['/inventario/items', 'lab8-servicios-externos.adoc'],
  ['/3scale/api/v1/party', 'lab9-migracion-3scale.adoc'], ['/3scale/api/v1/accounts', 'lab9-migracion-3scale.adoc'],
  ['/3scale/admin/audit-log', 'lab9-migracion-3scale.adoc'], ['/gobierno/v1/saldo', 'lab10-gobierno.adoc'],
  ['/socio/v1/pedidos', 'lab11-seguridad-b2b.adoc'], ['/v1/chat/completions', 'ia-practica.adoc'],
  ['/protocol/openid-connect/token', 'lab4.adoc'], ['/', 'lab3.adoc']
]);
let count = 0;
const tokens = [];
function scripts(item) {
  for (const event of item.event || []) {
    const code = event.script.exec.join('\n');
    new vm.Script(code);
    assert(!/setNextRequest|sendRequest|console\.log|setInterval/.test(code), 'Sin bucles/red secundaria ni impresión de tokens');
  }
}
scripts(collection);
function walk(items) {
  for (const item of items) {
    scripts(item);
    if (item.item) { walk(item.item); continue; }
    count++;
    assert(['GET', 'POST'].includes(item.request.method));
    const match = item.request.url.match(/^\{\{([A-Za-z][A-Za-z0-9]*)\}\}(\/.*)$/);
    assert(match, 'URL parametrizada: ' + item.request.url);
    assert(canonicalPaths.has(match[2]), 'Endpoint desconocido: ' + match[2]);
    if (workshopRoot && match[2] !== '/') {
      const source = fs.readFileSync(path.join(workshopRoot, 'modules/ROOT/pages', canonicalPaths.get(match[2])), 'utf8');
      assert(source.includes(match[2]), 'Endpoint ausente de fuente: ' + match[2]);
    }
    assert(item.event.some(event => event.listen === 'test'), 'Resultado esperado obligatorio');
    if (match[2].endsWith('/token')) tokens.push(item);
    if (item.request.body?.mode === 'raw') JSON.parse(item.request.body.raw);
  }
}
walk(collection.item);
for (const folder of collection.item) for (const sub of folder.item.filter(item => /Cuota|Plan básico 5\/min|Plan Bronze|Plan Silver/.test(item.name) && item.item)) {
  const statuses = sub.item.map(item => Number(item.event[0].script.exec[0].match(/HTTP (\d+)/)[1]));
  const firstLimited = statuses.indexOf(429);
  assert(firstLimited > 0, sub.name);
  assert(statuses.slice(0, firstLimited).every(code => code === 200));
  assert(statuses.slice(firstLimited).every(code => code === 429));
}
// Un fallo de login no conserva un token anterior ni guarda error_description.
for (const token of tokens) {
  for (const [code, payload, shouldStore] of [[200, {access_token: 'runtime-test-token'}, true], [401, {error: 'invalid_grant'}, false], [200, {}, false]]) {
    const saved = new Map([['jwt', 'stale'], ['bobJwt', 'stale'], ['m2mReadJwt', 'stale'], ['m2mWriteJwt', 'stale']]);
    const target = token.event[0].script.exec[0].match(/unset\('([^']+)'\)/)[1];
    const pm = {environment: {unset: key => saved.delete(key), set: (key, value) => saved.set(key, value)}, response: {code, json: () => payload}, test: () => {}};
    for (const event of token.event) vm.runInNewContext(event.script.exec.join('\n'), {pm});
    assert.equal(saved.get(target), shouldStore ? 'runtime-test-token' : undefined);
  }
}
const lab9 = collection.item.find(item => item.name.startsWith('Lab 9'));
const gold = lab9.item.find(item => item.name.includes('Gold'));
assert(gold.item.every(item => item.event[0].script.exec[0].includes('HTTP 200')), 'Gold es ilimitado');
const lab7 = collection.item.find(item => item.name.startsWith('Lab 7'));
assert.equal(lab7.item[0].request.auth.type, 'noauth', 'Cloud sin JWT');
const lab8 = collection.item.find(item => item.name.startsWith('Lab 8'));
const inventarioReq = lab8.item[0].item[1];
assert.equal(inventarioReq.request.url, '{{apiBaseUrl}}/inventario/items', 'Servicio externo pasa por Gateway');
console.log(`PASS: ${collection.item.length} carpetas, ${count} peticiones, ${variables.size} variables; rutas, cuotas y captura de tokens comprobadas sin tráfico.`);
if (!workshopRoot) console.log('SKIP: endpoints sin contrastar con las páginas (monta el repo como submódulo del workshop o define WORKSHOP_ROOT).');
