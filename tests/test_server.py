import json
import sys
from pathlib import Path
import threading
import unittest
from unittest.mock import patch
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.request
import urllib.error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class Upstream(BaseHTTPRequestHandler):
    calls = []

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        self.calls.append((self.path, self.headers.get('Authorization'), body))
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.end_headers()
        self.wfile.write(b'data: {"choices":[{"delta":{"content":"Bonjour"}}]}\n\ndata: [DONE]\n\n')

    def log_message(self, *args):
        pass


class ProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.upstream = ThreadingHTTPServer(('127.0.0.1', 0), Upstream)
        cls.proxy = ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        for instance in (cls.upstream, cls.proxy):
            threading.Thread(target=instance.serve_forever, daemon=True).start()
        cls.url = f'http://127.0.0.1:{cls.proxy.server_port}'

    @classmethod
    def tearDownClass(cls):
        for instance in (cls.proxy, cls.upstream):
            instance.shutdown()
            instance.server_close()

    def setUp(self):
        self.config = patch.multiple(server, API_KEY='test-secret-key', CHAT_PASSWORD='',
                                     BASE_URL=f'http://127.0.0.1:{self.upstream.server_port}/v1')
        self.config.start()
        self.addCleanup(self.config.stop)
        Upstream.calls.clear()

    def request(self, path, body=None, headers=None):
        req = urllib.request.Request(self.url + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={'Content-Type': 'application/json', **(headers or {})})
        try:
            response = urllib.request.urlopen(req, timeout=5)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            return response.status, response.read(), response.headers

    def test_stream_forwards_settings_and_keeps_key_out_of_response(self):
        payload = {'messages': [{'role': 'user', 'content': 'Bonjour'}], 'reasoning_effort': 'xhigh',
                   'temperature': 0.8, 'max_tokens': 4096, 'model': 'unwanted-model'}
        code, body, headers = self.request('/api/chat', payload)
        self.assertEqual(code, 200)
        self.assertIn(b'data: [DONE]', body)
        self.assertNotIn(b'test-secret-key', body)
        self.assertIn('text/event-stream', headers['Content-Type'])
        path, authorization, sent = Upstream.calls[0]
        self.assertEqual(path, '/v1/chat/completions')
        self.assertEqual(authorization, 'Bearer test-secret-key')
        self.assertEqual(sent['model'], server.MODEL)
        self.assertEqual(sent['reasoning_effort'], 'xhigh')
        self.assertEqual(sent['temperature'], 0.8)
        self.assertEqual(sent['max_tokens'], 4096)
        self.assertTrue(sent['stream'])

    def test_bad_effort_and_temperature_are_rejected_before_upstream(self):
        for settings in ({'reasoning_effort': 'high'}, {'temperature': 3}, {'temperature': True}, {'max_tokens': 9000}):
            with self.subTest(settings=settings):
                status, _, _ = self.request('/api/chat', {'messages': [{'role': 'user', 'content': 'Bonjour'}], **settings})
                self.assertEqual(status, 400)
        self.assertFalse(Upstream.calls)

    def test_missing_key_returns_actionable_error(self):
        with patch.object(server, 'API_KEY', ''):
            status, body, _ = self.request('/api/chat', {'messages': [{'role': 'user', 'content': 'Bonjour'}]})
        self.assertEqual(status, 503)
        self.assertIn(b'QWEN_API_KEY', body)

    def test_browser_cross_origin_request_is_rejected(self):
        status, _, _ = self.request('/api/chat', {'messages': [{'role': 'user', 'content': 'Bonjour'}]}, {'Origin': 'https://unrelated.example'})
        self.assertEqual(status, 403)
        self.assertFalse(Upstream.calls)

    def test_secrets_are_not_served_and_health_exposes_no_key(self):
        self.assertEqual(self.request('/.env')[0], 404)
        status, body, _ = self.request('/api/health')
        self.assertEqual(status, 200)
        self.assertTrue(json.loads(body)['configured'])
        self.assertNotIn(b'test-secret-key', body)

    def test_optional_password_protects_page_and_api(self):
        with patch.object(server, 'CHAT_PASSWORD', 'password'):
            for path in ('/', '/api/health'):
                self.assertEqual(self.request(path)[0], 401)

    def test_local_rendering_assets_and_fonts_are_served(self):
        for path, mime in (('/render.js', 'text/javascript'),
                           ('/vendor/highlight/highlight.min.js', 'text/javascript'),
                           ('/vendor/katex/katex.min.css', 'text/css'),
                           ('/vendor/katex/fonts/KaTeX_Main-Regular.woff2', 'font/woff2')):
            with self.subTest(path=path):
                status, body, headers = self.request(path)
                self.assertEqual(status, 200)
                self.assertTrue(body)
                self.assertIn(mime, headers['Content-Type'])

    def test_vendor_route_cannot_read_files_outside_vendor(self):
        for path in ('/vendor/../../.env', '/vendor/%2e%2e/%2e%2e/server.py', '/vendor/missing.js'):
            with self.subTest(path=path):
                self.assertEqual(self.request(path)[0], 404)


if __name__ == '__main__':
    unittest.main()
