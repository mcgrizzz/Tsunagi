"""HTTP integration and optional browser checks against this app's actual schema."""
import json
import os
import subprocess
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from tsunagi.app import app


def test_landing_page_and_reference():
    with TestClient(app, base_url="http://127.0.0.1") as client:
        page = client.get('/')
        assert page.status_code == 200
        assert page.headers['content-type'].startswith('text/html')
        assert page.headers['cache-control'] == 'no-store'
        assert 'Scalar.createApiReference' in page.text
        assert client.get('/docs').status_code == 200
        schema = client.get('/openapi.json').json()
        assert 'text/html' in schema['paths']['/']['get']['responses']['200']['content']
        # POST / remains the registered AnkiConnect RPC endpoint.
        assert 'post' in schema['paths']['/']


def test_openapi_describes_native_auth_without_applying_it_to_rpc_or_health():
    schema = app.openapi()
    schemes = schema['components']['securitySchemes']
    assert schemes['ApiKey']['in'] == 'header'
    assert schemes['ApiKey']['name'] == 'X-API-Key'
    assert schemes['BearerAuth']['scheme'] == 'bearer'
    for path in ('/v1/notes', '/v1/notes/query', '/actions'):
        for operation in schema['paths'][path].values():
            assert operation['security'] == [{'ApiKey': []}, {'BearerAuth': []}]
    assert not schema['paths']['/']['post'].get('security')
    assert not schema['paths']['/v1/health']['get'].get('security')
    assert app.openapi() == schema


@pytest.mark.skipif(not os.environ.get('TSUNAGI_BROWSER_PYTHON'), reason='Optional Playwright environment')
def test_playground_browser(tmp_path):
    schema = tmp_path / 'openapi.json'
    schema.write_text(json.dumps(app.openapi()))
    subprocess.run(
        [os.environ['TSUNAGI_BROWSER_PYTHON'],
         str(Path(__file__).resolve().parents[1] / 'tools/check_playground.py'),
         '--schema', str(schema)],
        check=True, timeout=90,
    )
