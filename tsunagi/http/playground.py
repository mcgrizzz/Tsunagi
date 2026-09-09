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
summary { cursor: pointer; } details { margin-top: 16px; }
input, select, textarea { font-weight: normal; }
.table-scroll { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; font-size: .9rem; }
th, td { text-align: left; vertical-align: top; padding: 10px; border-bottom: 1px solid light-dark(#ccd4dd, #414a56); overflow-wrap: anywhere; max-width: 400px; }
.example { padding: 3px 9px; font-size: .85rem; }
#result-title { margin-bottom: 4px; }
#status { min-height: 1.5em; } [hidden] { display: none !important; }
@media(max-width: 720px) { .grid { grid-template-columns: 1fr; } body { padding: 20px 12px; } }
</style>
</head>
<body>
<header><div><h1>Tsunagi</h1><span class="hint">API playground</span></div>
<nav aria-label="API reference"><a href="/docs">Swagger</a><a href="/redoc">ReDoc</a><a href="/openapi.json">OpenAPI</a></nav></header>
<p>Try a read-only query against your Anki collection. Start with a note search, or choose another task.</p>
<p id="status" class="hint" role="status" aria-live="polite">Loading available operations…</p>
<form id="form">
<fieldset id="controls" disabled>
<section class="panel">
<label for="operation">What would you like to do?</label><select id="operation"></select>
<p id="guide"></p>
<div id="parameters" class="grid"></div>
<div id="examples" class="actions" hidden><span class="hint">Try a search:</span></div>
<details id="advanced"><summary>Advanced query options</summary><div id="advanced-parameters" class="grid"></div></details>
<details id="authentication"><summary>API key (if required)</summary>
<label for="key">API key <small>Kept only until you close or reload this page.</small></label><input id="key" type="password" autocomplete="off" spellcheck="false"></details>
<div class="actions"><button id="run" class="primary" type="submit">Find notes</button></div>
<details id="request-details"><summary>Request details</summary>
<p id="description" class="hint"></p><pre id="preview">Select a task.</pre></details>
</section>
</fieldset>
</form>
<div class="actions"><button id="cancel" type="button" hidden>Cancel request</button></div>
<section class="panel" id="results" aria-live="polite">
<h2 id="result-title">Results</h2><p id="result-status" class="hint">Enter a search, or leave it blank, then choose Find notes.</p>
<div id="result-items" class="table-scroll"></div>
<div class="actions"><button id="next" type="button" hidden disabled>Load next page</button></div>
<details id="response-details" hidden><summary>Full JSON response</summary><pre id="response">No response yet.</pre></details>
<details id="sent-details" hidden><summary>Request that produced these results</summary><pre id="sent"></pre></details>
</section>
<script>
'use strict';
const el = id => document.getElementById(id);
const taskLabels = {
  listNotes: 'Find notes', listCards: 'Find cards', listDecks: 'Browse decks',
  listModels: 'Browse note types', listReviews: 'Browse review history',
  checkHealth: 'Check server connection', getCapabilities: 'Check supported features',
  getCollectionMeta: 'Inspect collection settings'
};
const taskHelp = {
  listNotes: 'Search just as you would in Anki’s browser. Choose Show cards on a result to see the cards made from that note.',
  listCards: 'Search for cards using Anki’s browser syntax. Leave the search blank to browse all cards.',
  checkHealth: 'Check that Tsunagi is running and see the installed versions.',
  getCapabilities: 'See which features your Anki version supports. FSRS support and whether it is enabled are listed separately.'
};
const fieldLabels = {search: 'Anki search', limit: 'Results per page', select: 'Fields to return',
  where: 'Field filters', shape: 'Response format', cursor: 'Page cursor'};
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

function chooseOperation() {
  current = operations.find(op => op.operationId === el('operation').value);
  fields = []; nextCursor = null;
  el('parameters').replaceChildren(); el('advanced-parameters').replaceChildren();
  el('advanced').open = false;
  el('guide').textContent = taskHelp[current?.operationId] || 'Choose your options below, then run the query.';
  el('run').textContent = taskLabels[current?.operationId] || current?.summary || 'Run query';
  el('result-title').textContent = 'Results';
  el('result-status').textContent = 'Ready. Choose ' + el('run').textContent + ' to run this query.';
  el('result-items').replaceChildren();
  el('sent-details').hidden = true; el('response-details').hidden = true;
  el('examples').replaceChildren(); el('examples').hidden = true;
  el('run').disabled = !current;
  el('description').textContent = current ? current.description || current.summary || '' : 'This workflow is unavailable on this server.';
  for (const param of current ? current.parameters : []) {
    if (!['path', 'query'].includes(param.in)) continue;
    const schema = resolve(param.schema);
    const type = schema.type || (schema.anyOf || []).find(s => s.type !== 'null')?.type;
    const label = document.createElement('label');
    label.textContent = (fieldLabels[param.name] || param.name) + (param.required ? ' *' : '');
    const options = schema.enum || (type === 'boolean' ? ['true', 'false'] : null);
    const input = document.createElement(options ? 'select' : type === 'array' ? 'textarea' : 'input');
    input.id = 'param-' + fields.length; input.dataset.parameter = param.name;
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
    if (param.name === 'search') {
      input.placeholder = 'e.g. deck:Japanese or tag:verb';
      help.textContent = 'Leave blank to browse everything. Anki search syntax works here.';
      el('examples').hidden = false;
      const caption = document.createElement('span'); caption.textContent = 'Try a search:';
      el('examples').append(caption);
      for (const example of ['tag:verb', 'is:due']) {
        const button = document.createElement('button'); button.type = 'button';
        button.className = 'example'; button.textContent = example;
        button.addEventListener('click', () => { input.value = example; input.dispatchEvent(new Event('input')); input.focus(); });
        el('examples').append(button);
      }
    }
    if (param.name === 'limit') help.textContent = 'How many results to show at a time.';
    label.append(input, help);
    const primary = param.required || param.name === 'search' || param.name === 'limit';
    el(primary ? 'parameters' : 'advanced-parameters').append(label);
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
  el('advanced').hidden = !el('advanced-parameters').children.length;
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
  el('next').disabled = !nextCursor || Boolean(controller);
  el('next').hidden = !nextCursor;
}

function renderResults(data, ok) {
  el('response-details').hidden = false;
  el('response-details').open = !ok || !Array.isArray(data?.items);
  if (!ok || !Array.isArray(data?.items)) return;
  const items = data.items;
  el('result-title').textContent = items.length + (items.length === 1 ? ' result' : ' results') + ' on this page';
  if (!items.length) {
    el('result-items').textContent = 'No matches. Try a broader search or clear the search to browse everything.';
    return;
  }
  const table = document.createElement('table');
  const head = table.createTHead().insertRow();
  for (const title of ['ID / value', 'Content preview', '']) { const th = document.createElement('th'); th.textContent = title; head.append(th); }
  const body = table.createTBody();
  for (const item of items) {
    const object = item !== null && typeof item === 'object' && !Array.isArray(item);
    const id = object ? item.id : item;
    const row = body.insertRow(); row.insertCell().textContent = id == null ? '—' : String(id);
    const content = object ? Object.fromEntries(Object.entries(item).filter(([key]) => key !== 'id')) : item;
    const preview = typeof content === 'string' ? content : Object.entries(content || {}).map(([name, value]) => name + ': ' + (typeof value === 'string' ? value : JSON.stringify(value))).join(' · ');
    row.insertCell().textContent = preview.length > 300 ? preview.slice(0, 300) + '…' : preview;
    const action = row.insertCell();
    if (current.operationId === 'listNotes' && object && Number.isSafeInteger(id) && operations.some(op => op.operationId === 'listCards' && op.parameters.some(p => p.name === 'search' && p.in === 'query'))) {
      const button = document.createElement('button'); button.type = 'button'; button.textContent = 'Show cards';
      button.addEventListener('click', () => {
        if (controller) return;
        el('operation').value = 'listCards'; chooseOperation();
        const search = fields.find(f => f.param.name === 'search');
        if (search) { search.input.value = 'nid:' + id; updatePreview(); send(); }
      });
      action.append(button);
    }
  }
  el('result-items').append(table);
}

async function send() {
  if (controller || !current || !el('form').reportValidity()) return;
  const request = buildRequest();
  controller = new AbortController();
  const timer = setTimeout(() => controller?.abort(), 30000);
  el('controls').disabled = true; el('cancel').hidden = false;
  el('result-items').replaceChildren();
  el('result-title').textContent = current.summary || 'Results';
  el('response-details').hidden = true;
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
    renderResults(data, result.ok);
    if (result.status === 401) { el('authentication').open = true; }
    if (result.ok && typeof data?.next_cursor === 'string' && data.next_cursor && fields.some(f => f.param.name === 'cursor' && f.param.in === 'query')) nextCursor = data.next_cursor;
  } catch (error) {
    el('result-status').textContent = error.name === 'AbortError' ? 'Request cancelled or timed out (30 seconds).' : 'Request failed: ' + error.message;
    el('response').textContent = 'No response received.';
    el('response-details').hidden = false; el('response-details').open = true;
  } finally {
    clearTimeout(timer); controller = null;
    el('controls').disabled = false; el('cancel').hidden = true; updatePreview();
  }
}

el('operation').addEventListener('change', chooseOperation);
el('key').addEventListener('input', updatePreview);
el('form').addEventListener('submit', event => { event.preventDefault(); send(); });
el('next').addEventListener('click', () => {
  const cursor = fields.find(f => f.param.name === 'cursor' && f.param.in === 'query');
  if (nextCursor && cursor) { cursor.input.value = nextCursor; updatePreview(); send(); }
});
el('cancel').addEventListener('click', () => controller?.abort());

async function initialize() {
  try {
    const result = await fetch('/openapi.json', {cache: 'no-store', redirect: 'error'});
    if (!result.ok) throw new Error('HTTP ' + result.status);
    spec = await result.json(); operations = readOperations(spec);
    const preferred = Object.keys(taskLabels);
    operations.sort((a, b) => (preferred.indexOf(a.operationId) < 0 ? 99 : preferred.indexOf(a.operationId)) - (preferred.indexOf(b.operationId) < 0 ? 99 : preferred.indexOf(b.operationId)));
    el('operation').replaceChildren(...operations.map(op => new Option(taskLabels[op.operationId] || op.summary || op.operationId, op.operationId)));
    chooseOperation(); el('controls').disabled = false;
    el('status').textContent = 'Connected to ' + location.origin + ' · API release ' + spec.info.version;
  } catch (error) {
    el('status').textContent = 'Could not load OpenAPI: ' + error.message + '. Reload this page to retry.';
  }
}
initialize();
</script>
</body>
</html>'''
