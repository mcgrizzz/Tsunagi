"""Self-contained, same-origin API playground; operations come from live OpenAPI."""

PLAYGROUND_HTML = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tsunagi · API playground</title>
<style>
:root { color-scheme: light dark; font: 16px/1.5 system-ui, sans-serif; }
body { max-width: 1120px; margin: auto; padding: 28px 20px 60px; }
header, nav, .actions { display: flex; align-items: center; gap: 16px; flex-wrap: wrap; }
header { justify-content: space-between; margin-bottom: 24px; }
h1 { margin: 0; font-size: 1.8rem; } h2 { font-size: 1.2rem; margin-top: 0; }
a { color: light-dark(#175f97, #8dcaff); }
fieldset { border: 0; padding: 0; margin: 0; min-width: 0; }
.panel { padding: 20px; border: 1px solid light-dark(#ccd4dd, #414a56); border-radius: 10px; margin-top: 20px; }
.grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
label { display: block; font-weight: 600; margin-top: 14px; }
input, select, textarea, button { font: inherit; border: 1px solid light-dark(#8b99a7, #687584); border-radius: 5px; padding: 8px 10px; }
input, select, textarea { box-sizing: border-box; width: 100%; margin-top: 5px; background: light-dark(#fff, #202731); }
button { cursor: pointer; } button:disabled { cursor: default; opacity: .5; }
button.primary { background: #185d92; color: white; border-color: #185d92; }
small, .hint { color: light-dark(#4b5969, #b1bfcd); }
small { display: block; font-weight: normal; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; max-height: 500px; overflow: auto; background: light-dark(#f1f5f9, #171e27); padding: 14px; border-radius: 5px; font-size: .85rem; }
.actions { margin-top: 16px; }
#status { min-height: 1.5em; } [hidden] { display: none !important; }
@media(max-width: 720px) { .grid { grid-template-columns: 1fr; } body { padding: 20px 12px; } }
</style>
</head>
<body>
<header><div><h1>Tsunagi</h1><span class="hint">API playground</span></div>
<nav aria-label="API reference"><a href="/docs">Swagger</a><a href="/redoc">ReDoc</a><a href="/openapi.json">OpenAPI</a></nav></header>
<p>Explore your running Anki collection. Choose a workflow, edit its parameters, and inspect each request and response. These workflows only read data.</p>
<p id="status" role="status" aria-live="polite">Loading available operations…</p>
<form id="form">
<fieldset id="controls" disabled>
<section class="panel">
<div class="grid"><div><label for="workflow">Workflow</label><select id="workflow"></select></div>
<div><label for="key">API key <small>Optional when authentication is off. Kept only in this page’s memory.</small></label><input id="key" type="password" autocomplete="off" spellcheck="false"></div></div>
<p id="guide"></p>
<label for="operation">Step / operation</label><select id="operation"></select>
<p id="description" class="hint"></p>
<div id="parameters" class="grid"></div>
<div class="actions"><button id="run" class="primary" type="submit">Send request</button>
<button id="next" type="button" disabled>Next page</button>
<button id="step" type="button" disabled>Next step</button></div>
</section>
</fieldset>
</form>
<div class="actions"><button id="cancel" type="button" hidden>Cancel request</button></div>
<div class="grid">
<section class="panel"><h2>Request preview</h2><pre id="preview">Select an operation.</pre></section>
<section class="panel"><h2>Response</h2><p id="result-status" class="hint">No request sent yet.</p>
<details id="sent-details" hidden><summary>Request sent (API key redacted)</summary><pre id="sent"></pre></details>
<pre id="response">Responses will appear here.</pre></section>
</div>
<script>
'use strict';
const el = id => document.getElementById(id);
const workflows = [
  {name: 'Check runtime and capabilities', ids: ['checkHealth', 'getCapabilities', 'getCollectionMeta'],
   guide: 'Start with server versions, then inspect capabilities and collection settings. FSRS support and whether FSRS is enabled are separate values; check an operation’s availability and unsupported options before using it in Swagger.'},
  {name: 'Find notes and their cards', ids: ['listNotes', 'listCards'],
   guide: 'Search notes using Anki syntax (for example, tag:verb). In the next step, use nid:<note ID> in the card search to inspect cards generated from a note. Use Next page to continue the same query.'},
  {name: 'Browse collection data', ids: ['listDecks', 'listModels', 'listCards', 'listReviews'],
   guide: 'Inspect decks and note types, then cards and review history. Start with a small page; edit select, filters, or search before sending. Each parameter’s description comes from OpenAPI.'},
  {name: 'Explore all JSON read operations', ids: null,
   guide: 'Choose any available JSON GET operation. Enter required path values such as a job ID. Swagger provides the complete reference, including mutations and streaming endpoints.'}
];
let spec, operations = [], current, fields = [], nextCursor = null, controller = null;

function resolve(value) {
  while (value && value.$ref) {
    if (!value.$ref.startsWith('#/')) throw new Error('Unsupported external schema reference');
    value = value.$ref.slice(2).split('/').reduce((v, k) => v[k.replace(/~1/g, '/').replace(/~0/g, '~')], spec);
  }
  return value || {};
}

function readOperations(schema) {
  return Object.entries(schema.paths).flatMap(([path, item]) => {
    const op = item.get;
    if (!op || path === '/' || path === '/v1/events') return [];
    const content = resolve((op.responses || {})['200']).content || {};
    if (!content['application/json'] || content['text/event-stream']) return [];
    // Operation parameters override path-item parameters with the same name/location.
    const params = new Map();
    for (const raw of [...(item.parameters || []), ...(op.parameters || [])]) {
      const p = resolve(raw); params.set(p.in + ':' + p.name, p);
    }
    return [{path, ...op, parameters: [...params.values()]}];
  });
}

function chooseWorkflow() {
  const flow = workflows[Number(el('workflow').value)];
  el('guide').textContent = flow.guide;
  const selected = flow.ids ? flow.ids.map(id => operations.find(op => op.operationId === id)).filter(Boolean) : operations;
  el('operation').replaceChildren(...selected.map(op => new Option(op.summary || op.operationId, op.operationId)));
  chooseOperation();
}

function chooseOperation() {
  current = operations.find(op => op.operationId === el('operation').value);
  fields = []; nextCursor = null;
  el('parameters').replaceChildren();
  el('run').disabled = !current;
  el('step').disabled = el('operation').selectedIndex >= el('operation').options.length - 1;
  el('description').textContent = current ? current.description || current.summary || '' : 'This workflow is unavailable on this server.';
  for (const param of current ? current.parameters : []) {
    if (!['path', 'query'].includes(param.in)) continue;
    const schema = resolve(param.schema);
    const type = schema.type || (schema.anyOf || []).find(s => s.type !== 'null')?.type;
    const label = document.createElement('label');
    label.textContent = param.name + (param.required ? ' *' : '');
    const options = schema.enum || (type === 'boolean' ? ['true', 'false'] : null);
    const input = document.createElement(options ? 'select' : type === 'array' ? 'textarea' : 'input');
    input.id = 'param-' + fields.length;
    label.htmlFor = input.id;
    if (options) input.replaceChildren(new Option('Use server default', ''), ...options.map(v => new Option(String(v), String(v))));
    input.required = Boolean(param.required);
    if (type === 'integer' || type === 'number') {
      input.type = 'number'; input.step = type === 'integer' ? '1' : 'any';
      if (schema.minimum !== undefined) input.min = schema.minimum;
      if (schema.maximum !== undefined) input.max = schema.maximum;
    }
    if (param.name === 'limit' && param.in === 'query') input.value = Math.min(10, schema.maximum ?? 10);
    else if (schema.default !== undefined) input.value = Array.isArray(schema.default) ? schema.default.join('\n') : schema.default;
    const help = document.createElement('small');
    help.textContent = (param.description || schema.description || param.in + ' parameter') + (type === 'array' ? ' Enter one value per line.' : '');
    label.append(input, help); el('parameters').append(label);
    fields.push({param, input, type});
    input.addEventListener('input', () => {
      nextCursor = null;
      if (param.name !== 'cursor') {
        const cursor = fields.find(f => f.param.name === 'cursor' && f.param.in === 'query');
        if (cursor) cursor.input.value = '';
      }
      updatePreview();
    });
  }
  updatePreview();
}

function buildRequest() {
  if (!current) return null;
  let path = current.path;
  const query = new URLSearchParams();
  for (const {param, input, type} of fields) {
    const value = input.value;
    if (param.in === 'path') path = path.replace('{' + param.name + '}', encodeURIComponent(value));
    else if (value !== '') {
      const values = type === 'array' ? value.split('\n').filter(v => v !== '') : [value];
      values.forEach(v => query.append(param.name, v));
    }
  }
  const url = new URL(path, location.origin);
  url.search = query.toString();
  if (url.origin !== location.origin) throw new Error('Requests must use this server');
  const headers = {Accept: 'application/json'};
  if (el('key').value) headers['X-API-Key'] = el('key').value;
  const display = 'GET ' + url.href + '\nAccept: application/json' + (headers['X-API-Key'] ? '\nX-API-Key: [redacted]' : '');
  return {url, headers, display};
}

function updatePreview() {
  el('preview').textContent = buildRequest()?.display || 'No operation available.';
  el('next').disabled = !nextCursor;
}

async function send() {
  if (controller || !current || !el('form').reportValidity()) return;
  const request = buildRequest();
  controller = new AbortController();
  const timer = setTimeout(() => controller?.abort(), 30000);
  el('controls').disabled = true; el('cancel').hidden = false;
  nextCursor = null; el('next').disabled = true;
  el('sent-details').hidden = false; el('sent').textContent = request.display;
  el('response').textContent = 'Waiting…'; el('result-status').textContent = 'Request in progress';
  const start = performance.now();
  try {
    const result = await fetch(request.url, {method: 'GET', headers: request.headers, signal: controller.signal, cache: 'no-store', redirect: 'error'});
    const body = await result.text();
    let data;
    try { data = JSON.parse(body); } catch { /* Show non-JSON errors verbatim. */ }
    el('response').textContent = data === undefined ? body : JSON.stringify(data, null, 2);
    el('result-status').textContent = 'HTTP ' + result.status + ' · ' + Math.round(performance.now() - start) + ' ms' + (result.status === 401 ? ' · Enter your API key and retry.' : '');
    if (result.ok && typeof data?.next_cursor === 'string' && data.next_cursor && fields.some(f => f.param.name === 'cursor' && f.param.in === 'query')) nextCursor = data.next_cursor;
  } catch (error) {
    el('result-status').textContent = error.name === 'AbortError' ? 'Request cancelled or timed out (30 seconds).' : 'Request failed: ' + error.message;
    el('response').textContent = 'No response received.';
  } finally {
    clearTimeout(timer); controller = null;
    el('controls').disabled = false; el('cancel').hidden = true; updatePreview();
  }
}

el('workflow').addEventListener('change', chooseWorkflow);
el('operation').addEventListener('change', chooseOperation);
el('key').addEventListener('input', updatePreview);
el('form').addEventListener('submit', event => { event.preventDefault(); send(); });
el('next').addEventListener('click', () => {
  const cursor = fields.find(f => f.param.name === 'cursor' && f.param.in === 'query');
  if (nextCursor && cursor) { cursor.input.value = nextCursor; updatePreview(); send(); }
});
el('step').addEventListener('click', () => { el('operation').selectedIndex += 1; chooseOperation(); });
el('cancel').addEventListener('click', () => controller?.abort());

async function initialize() {
  try {
    const result = await fetch('/openapi.json', {cache: 'no-store', redirect: 'error'});
    if (!result.ok) throw new Error('HTTP ' + result.status);
    spec = await result.json(); operations = readOperations(spec);
    el('workflow').replaceChildren(...workflows.map((flow, i) => new Option(flow.name, String(i))));
    chooseWorkflow(); el('controls').disabled = false;
    el('status').textContent = 'Connected to ' + location.origin + ' · API release ' + spec.info.version;
  } catch (error) {
    el('status').textContent = 'Could not load OpenAPI: ' + error.message + '. Reload this page to retry.';
  }
}
initialize();
</script>
</body>
</html>'''
