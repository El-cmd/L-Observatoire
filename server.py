"""L’Observatoire: static UI and same-origin streaming proxy, standard library only."""
import base64
import hmac
import json
import math
import os
from pathlib import Path
import socket
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import urllib.error
import urllib.request

ROOT = Path(__file__).parent / 'public'
MODEL = os.getenv('QWEN_MODEL', 'qwen3.8-27b-abliterated')
BASE_URL = os.getenv('QWEN_BASE_URL', 'https://votre-api.example/v1').rstrip('/')
API_KEY = os.getenv('QWEN_API_KEY', '')
CHAT_USER = os.getenv('CHAT_USER', 'vloth')
CHAT_PASSWORD = os.getenv('CHAT_PASSWORD', '')
MAX_BODY = 512 * 1024


def validate(body):
    if not isinstance(body, dict):
        raise ValueError('La requête doit être un objet JSON.')
    messages = body.get('messages')
    if not isinstance(messages, list) or not 1 <= len(messages) <= 100:
        raise ValueError('La conversation doit contenir entre 1 et 100 messages.')
    clean = []
    for message in messages:
        if not isinstance(message, dict) or message.get('role') not in ('system', 'user', 'assistant'):
            raise ValueError('Rôle de message invalide.')
        if not isinstance(message.get('content'), str) or not message['content'].strip():
            raise ValueError('Un message ne peut pas être vide.')
        clean.append({'role': message['role'], 'content': message['content']})
    effort = body.get('reasoning_effort', 'none')
    if effort not in ('none', 'low', 'medium', 'xhigh'):
        raise ValueError('Niveau de raisonnement invalide.')
    temperature = body.get('temperature', 0.7)
    if type(temperature) not in (int, float) or not math.isfinite(temperature) or not 0 <= temperature <= 2:
        raise ValueError('La température doit être comprise entre 0 et 2.')
    tokens = body.get('max_tokens', 2048)
    if type(tokens) is not int or not 128 <= tokens <= 8192:
        raise ValueError('La limite de réponse doit être comprise entre 128 et 8192 tokens.')
    return {'model': MODEL, 'messages': clean, 'reasoning_effort': effort,
            'temperature': temperature, 'max_tokens': tokens, 'stream': True,
            'stream_options': {'include_usage': True}}


class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def log_message(self, fmt, *args):
        # Request bodies and upstream credentials are never logged.
        super().log_message(fmt, *args)

    def security_headers(self):
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")

    def authorized(self):
        if not CHAT_PASSWORD:
            return True
        expected = 'Basic ' + base64.b64encode(f'{CHAT_USER}:{CHAT_PASSWORD}'.encode()).decode()
        if hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            return True
        self.send_response(401)
        self.security_headers()
        self.send_header('WWW-Authenticate', 'Basic realm="Observatoire", charset="UTF-8"')
        self.send_header('Content-Length', '0')
        self.send_header('Connection', 'close')
        self.end_headers()
        self.close_connection = True
        return False

    def respond(self, status, obj):
        data = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.security_headers()
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if not self.authorized():
            return
        if self.path == '/api/health':
            self.respond(200, {'configured': bool(API_KEY), 'model': MODEL})
            return
        files = {'/': ('index.html', 'text/html'), '/app.js': ('app.js', 'text/javascript'), '/render.js': ('render.js', 'text/javascript'),
                 '/style.css': ('style.css', 'text/css'), '/favicon.svg': ('favicon.svg', 'image/svg+xml')}
        from urllib.parse import unquote
        path = unquote(self.path.split('?')[0])
        route = files.get(path)
        if path.startswith('/vendor/'):
            asset = (ROOT / path.lstrip('/')).resolve()
            types = {'.js': 'text/javascript', '.css': 'text/css', '.woff2': 'font/woff2', '.woff': 'font/woff', '.ttf': 'font/ttf'}
            if asset.is_relative_to((ROOT / 'vendor').resolve()) and asset.is_file() and asset.suffix in types:
                route = (str(asset.relative_to(ROOT)), types[asset.suffix])
        if not route:
            self.respond(404, {'error': 'Page introuvable.'})
            return
        data = (ROOT / route[0]).read_bytes()
        self.send_response(200)
        self.security_headers()
        self.send_header('Content-Type', route[1] + '; charset=utf-8')
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-cache')
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        if not self.authorized():
            return
        # Block cross-origin browser submissions to this local proxy.
        origin = self.headers.get('Origin')
        if origin:
            from urllib.parse import urlsplit
            if urlsplit(origin).netloc != self.headers.get('Host'):
                self.close_connection = True
                self.respond(403, {'error': 'Origine non autorisée.'})
                return
        if self.path != '/api/chat':
            self.close_connection = True
            self.respond(404, {'error': 'Route introuvable.'})
            return
        try:
            length = int(self.headers.get('Content-Length', '0'))
            if not 0 < length <= MAX_BODY or self.headers.get('Transfer-Encoding'):
                self.close_connection = True
                self.respond(413, {'error': 'Requête trop volumineuse ou vide (512 Ko maximum).'})
                return
            payload = validate(json.loads(self.rfile.read(length)))
        except (ValueError, UnicodeDecodeError):
            self.close_connection = True
            self.respond(400, {'error': 'Requête invalide : vérifie les messages et les réglages.'})
            return
        if not API_KEY:
            self.respond(503, {'error': 'Ajoute QWEN_API_KEY dans le fichier .env puis relance le serveur.'})
            return
        req = urllib.request.Request(BASE_URL + '/chat/completions', data=json.dumps(payload).encode(),
                                     headers={'Authorization': 'Bearer ' + API_KEY, 'Content-Type': 'application/json', 'Accept': 'text/event-stream'})
        try:
            upstream = urllib.request.urlopen(req, timeout=190)
        except urllib.error.HTTPError as error:
            with error:
                detail = error.read(8192).decode(errors='replace').replace(API_KEY, '[masqué]')
            self.respond(error.code if 400 <= error.code <= 599 else 502,
                         {'error': f'L’API Qwen a répondu HTTP {error.code}.', 'detail': detail})
            return
        except (urllib.error.URLError, TimeoutError, OSError):
            self.respond(502, {'error': 'Le serveur Qwen est inaccessible. Vérifie le tunnel et QWEN_BASE_URL.'})
            return
        with upstream:
            if 'text/event-stream' not in upstream.headers.get('Content-Type', ''):
                self.respond(502, {'error': 'L’API n’a pas renvoyé le flux SSE attendu.'})
                return
            self.send_response(200)
            self.security_headers()
            self.send_header('Content-Type', 'text/event-stream; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache, no-transform')
            self.send_header('X-Accel-Buffering', 'no')
            self.send_header('Connection', 'close')
            self.end_headers()
            self.close_connection = True
            try:
                while chunk := upstream.read1(8192):
                    self.wfile.write(chunk)
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, TimeoutError, socket.timeout, OSError):
                # The browser reports an interrupted stream; context manager closes upstream.
                pass


def main():
    server = ThreadingHTTPServer((os.getenv('HOST', '127.0.0.1'), int(os.getenv('PORT', '8080'))), Handler)
    print(f'L’Observatoire : http://{server.server_address[0]}:{server.server_address[1]}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
