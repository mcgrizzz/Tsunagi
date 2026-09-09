"""Exercise the playground in Chromium with an actual OpenAPI schema and fake data.

Run via test_playground.py with TSUNAGI_BROWSER_PYTHON pointing to a Python
environment containing Playwright and its Chromium browser. No Anki data changes.
"""
import argparse
import json
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
    args = parser.parse_args()
    schema = json.loads(args.schema.read_text())
    html = runpy.run_path(str(Path(__file__).resolve().parents[1] / 'tsunagi/http/playground.py'))['PLAYGROUND_HTML']

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200)
            self.send_header('Content-Type', 'application/json' if self.path == '/openapi.json' else 'text/html')
            self.end_headers()
            self.wfile.write(json.dumps(schema).encode() if self.path == '/openapi.json' else html.encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    origin = f'http://127.0.0.1:{server.server_port}'
    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch()
            page = browser.new_page(viewport={'width': 1200, 'height': 1000})
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            requests = []
            pending = []
            mode = {'value': 'success'}

            def api(route):
                request = route.request
                requests.append(request)
                if mode['value'] == 'unauthorized':
                    route.fulfill(status=401, json={'detail': 'Invalid or missing API key'})
                elif mode['value'] == 'failure':
                    route.abort('failed')
                elif mode['value'] == 'pending':
                    pending.append(route)
                    return
                else:
                    cursor = parse_qs(urlsplit(request.url).query).get('cursor')
                    route.fulfill(json={'items': [{'id': 42, 'text': '<img src=x onerror="window.injected=true">'}],
                                        'next_cursor': None if cursor else 'page+2/=', 'stats': {}})

            page.route('**/v1/**', api)
            page.goto(origin)
            expect(page.locator('#status')).to_contain_text('Connected to')
            assert requests == [], 'Opening the page must not run a collection request'
            page.locator('#run').click()
            expect(page.locator('#result-status')).to_contain_text('HTTP 200')
            assert urlsplit(requests[-1].url).path == '/v1/health'
            page.locator('#step').click()
            expect(page.locator('#operation')).to_have_value('getCapabilities')
            page.locator('#run').click()
            expect(page.locator('#result-status')).to_contain_text('HTTP 200')
            assert urlsplit(requests[-1].url).path == '/v1/capabilities'

            page.locator('#workflow').select_option('1')
            search = page.get_by_label('search', exact=False)
            search.fill('deck:"日本" tag:a&b')
            page.get_by_label('where', exact=False).fill('id>10\nid<100')
            page.locator('#key').fill('test-secret')
            expect(page.locator('#preview')).not_to_contain_text('test-secret')
            page.locator('#run').click()
            expect(page.locator('#result-status')).to_contain_text('HTTP 200')
            sent = requests[-1]
            assert sent.headers['x-api-key'] == 'test-secret'
            query = parse_qs(urlsplit(sent.url).query)
            assert query['search'] == ['deck:"日本" tag:a&b']
            assert query['where'] == ['id>10', 'id<100']
            assert query['limit'] == ['10']
            assert page.locator('#response img').count() == 0
            assert page.evaluate('window.injected') is None
            expect(page.locator('#sent')).not_to_contain_text('test-secret')
            assert page.evaluate('localStorage.length + sessionStorage.length') == 0
            page.locator('#next').click()
            expect(page.locator('#result-status')).to_contain_text('HTTP 200')
            assert parse_qs(urlsplit(requests[-1].url).query)['cursor'] == ['page+2/=']
            expect(page.locator('#next')).to_be_disabled()
            search.fill('nid:42')
            expect(page.get_by_label('cursor', exact=False)).to_have_value('')
            page.locator('#step').click()
            expect(page.locator('#operation')).to_have_value('listCards')
            expect(page.locator('#next')).to_be_disabled()

            mode['value'] = 'unauthorized'
            page.locator('#run').click()
            expect(page.locator('#result-status')).to_contain_text('401')
            expect(page.locator('#next')).to_be_disabled()
            mode['value'] = 'failure'
            page.locator('#run').click()
            expect(page.locator('#result-status')).to_contain_text('Request failed')
            mode['value'] = 'pending'
            page.locator('#run').click()
            expect(page.locator('#run')).to_be_disabled()
            page.locator('#cancel').click()
            expect(page.locator('#result-status')).to_contain_text('cancelled')
            expect(page.locator('#run')).to_be_enabled()
            for route in pending:
                route.abort()
            page.unroute('**/v1/**', api)
            mode['value'] = 'success'
            page.route('**/v1/**', api)

            page.locator('#workflow').select_option('3')
            page.locator('#operation').select_option('getJob')
            previous = len(requests)
            page.locator('#run').click()
            assert len(requests) == previous, 'Required path parameters must be filled'
            page.get_by_label('job_id', exact=False).fill('a/b ?#')
            page.locator('#run').click()
            expect(page.locator('#result-status')).to_contain_text('HTTP 200')
            assert urlsplit(requests[-1].url).path == '/v1/jobs/a%2Fb%20%3F%23'

            # Schema changes, not a hard-coded route inventory, control the form.
            schema['paths']['/v1/notes']['get']['parameters'].append({
                'name': 'new_filter', 'in': 'query', 'schema': {'type': 'string'}})
            del schema['paths']['/v1/capabilities']
            page.reload()
            expect(page.locator('#status')).to_contain_text('Connected to')
            assert page.locator('#operation option[value="getCapabilities"]').count() == 0
            page.locator('#workflow').select_option('1')
            expect(page.get_by_label('new_filter', exact=False)).to_be_visible()
            page.get_by_label('new_filter', exact=False).fill('schema-driven')
            page.locator('#run').click()
            expect(page.locator('#result-status')).to_contain_text('HTTP 200')
            assert parse_qs(urlsplit(requests[-1].url).query)['new_filter'] == ['schema-driven']
            if args.screenshot:
                page.screenshot(path=str(args.screenshot), full_page=True)
            page.set_viewport_size({'width': 390, 'height': 844})
            assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
            assert not errors, errors
            browser.close()
    finally:
        server.shutdown()
        server.server_close()
        thread.join()
    print('Playground browser checks passed')


if __name__ == '__main__':
    main()
