"""Check Scalar's real browser console against generated OpenAPI and fake data."""
import argparse
import json
import os
import re
import runpy
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--schema', type=Path, required=True)
    parser.add_argument('--screenshot', type=Path)
    parser.add_argument('--bundle', type=Path, default=os.environ.get('TSUNAGI_SCALAR_BUNDLE'))
    args = parser.parse_args()
    schema = json.loads(args.schema.read_text())
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tsunagi/http/playground.py'))

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json' if self.path == '/openapi.json' else 'text/html')
            self.end_headers()
            self.wfile.write(json.dumps(schema).encode() if self.path == '/openapi.json' else module['PLAYGROUND_HTML'].encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 1400, 'height': 1000})
            page.set_default_timeout(10000)
            errors, requests, external_api_requests = [], [], []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.on('request', lambda req: external_api_requests.append(req.url)
                    if '/v1/' in req.url and not req.url.startswith(origin + '/') else None)
            if args.bundle:
                page.route(module['SCALAR_SCRIPT_URL'], lambda route: route.fulfill(path=str(args.bundle), content_type='text/javascript'))

            def api(route):
                request = route.request
                requests.append(request)
                if request.headers.get('x-api-key') != 'scalar-test-key':
                    route.fulfill(status=401, json={'detail': 'Invalid or missing API key'})
                else:
                    route.fulfill(json={'items': [{'id': 42, 'text': 'scalar-browser-result'}], 'next_cursor': None, 'stats': {}})

            page.route('**/v1/**', api)
            page.goto(origin)
            expect(page.get_by_role('heading', name='Overview', exact=True)).to_be_visible()
            expect(page.locator('#loading')).to_be_hidden()
            assert requests == [], 'Opening the reference must not query the collection'
            if args.screenshot:
                page.screenshot(path=str(args.screenshot), full_page=False)
            page.get_by_role('button', name='Open Group - Notes', exact=True).click()
            page.get_by_text('List notes', exact=True).first.click()
            page.get_by_role('button', name='Test Request').filter(has_text='(get /v1/notes)').click()
            dialog = page.get_by_role('dialog')
            expect(dialog).to_be_visible()
            dialog.locator('input[type=text]').first.fill('scalar-test-key')
            for name, value in [('search', 'deck:"日本" tag:a&b'), ('limit', '7')]:
                field = dialog.locator(f'tr[id="{name}"] [contenteditable=true]').last
                field.click()
                field.press('ControlOrMeta+A')
                field.press_sequentially(value)
                field.press('Tab')
                dialog.get_by_role('checkbox', name=f'Include {name} in request', exact=True).check()
            # Scalar commits editor changes asynchronously; wait for its code
            # example to reflect the edited request before sending it.
            if not dialog.locator('pre').first.is_visible():
                dialog.get_by_role('button', name=re.compile(r'^Code Snippet')).click()
            expect(dialog.locator('pre').first).to_contain_text('search=')
            expect(dialog.locator('pre').first).to_contain_text('limit=7')
            dialog.get_by_role('button', name=re.compile(r'^Send get request to')).click()
            expect(dialog).to_contain_text('scalar-browser-result')
            sent = requests[-1]
            assert sent.method == 'GET' and urlsplit(sent.url).path == '/v1/notes'
            query = parse_qs(urlsplit(sent.url).query)
            assert query.get('search') == ['deck:"日本" tag:a&b'], [(r.method, r.url) for r in requests]
            assert query['limit'] == ['7']
            assert sent.headers['x-api-key'] == 'scalar-test-key'
            dialog.get_by_role('button', name='Close Client', exact=True).click()

            page.get_by_text('Query notes (POST)', exact=True).first.click()
            page.get_by_role('button', name='Test Request').filter(has_text='(post /v1/notes/query)').click()
            expect(dialog).to_be_visible()
            payload = {'search': 'nid:42', 'limit': 2}
            editor = dialog.locator('.cm-content[contenteditable=true]')
            editor.fill(json.dumps(payload))
            if not dialog.locator('pre').first.is_visible():
                dialog.get_by_role('button', name=re.compile(r'^Code Snippet')).click()
            expect(dialog.locator('pre').first).to_contain_text('nid:42')
            dialog.get_by_role('button', name=re.compile(r'^Send post request to')).click()
            expect(dialog).to_contain_text('scalar-browser-result')
            sent = requests[-1]
            assert sent.method == 'POST' and urlsplit(sent.url).path == '/v1/notes/query'
            assert sent.post_data_json == payload
            assert sent.headers['x-api-key'] == 'scalar-test-key'
            assert sent.headers['content-type'].startswith('application/json')
            dialog.locator('input[type=text]').first.fill('wrong-key')
            expect(dialog.locator('pre').first).to_contain_text('wrong-key')
            dialog.get_by_role('button', name=re.compile(r'^Send post request to')).click()
            expect(dialog).to_contain_text('Invalid or missing API key')
            storage = page.evaluate('JSON.stringify({local: {...localStorage}, session: {...sessionStorage}})')
            assert 'scalar-test-key' not in storage and 'wrong-key' not in storage
            assert not external_api_requests, external_api_requests
            dialog.get_by_role('button', name='Close Client', exact=True).click()
            page.reload()
            expect(page.get_by_role('heading', name='Overview', exact=True)).to_be_visible()
            expect(page.locator('input[type=text]').first).to_have_value('')
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors

            # A blocked CDN leaves working reference links instead of a blank page.
            fallback = browser.new_page()
            fallback.route(module['SCALAR_SCRIPT_URL'], lambda route: route.abort())
            fallback.goto(origin)
            expect(fallback.locator('#loading')).to_contain_text('Could not load Scalar')
            expect(fallback.get_by_role('link', name='Swagger', exact=True)).to_be_visible()
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('Scalar browser checks passed: reference, GET edits, POST body, auth, response, current origin, fallback')


if __name__ == '__main__':
    main()
