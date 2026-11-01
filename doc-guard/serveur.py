"""HTTP front of doc-guard, the only service that opens documents sent by users. It has no
network access, no data and no secrets; each document is opened by lecteur.py in a process of
its own, killed after a delay, so that a malicious or huge file stops only that process.

    GET  /health                      -> {"ok": true}
    POST /analyse?name=<file name>    -> pages of a PDF (segments, text, reason to read the image)
                                         or the Markdown of a Word or text file
    POST /page?number=<n>&side=<px>   -> JPEG of one page of the PDF sent
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

MAX_BODY = 20 * 1024 * 1024
HERE = Path(__file__).parent
# Documents opened at the same time; the others wait for a slot.
SLOTS = threading.BoundedSemaphore(3)


class Handler(BaseHTTPRequestHandler):
    def reply(self, status: int, body: bytes, kind: str = 'application/json'):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def error(self, status: int, message: str):
        self.reply(status, json.dumps({'error': message}, ensure_ascii=False).encode())

    def do_GET(self):
        if self.path == '/health':
            self.reply(200, b'{"ok":true}')
        else:
            self.error(404, 'Route inconnue.')

    def do_POST(self):
        url = urlparse(self.path)
        query = {key: values[0] for key, values in parse_qs(url.query).items()}
        length = int(self.headers.get('Content-Length') or 0)
        if not 0 < length <= MAX_BODY:
            self.error(413, 'Document vide ou trop lourd (20 Mo au maximum).')
            return
        body = self.rfile.read(length)
        if url.path == '/analyse':
            extension = Path(query.get('name', '')).suffix.lower()
            extension = extension if re.fullmatch(r'\.[a-z0-9]{1,10}', extension) else ''
            self.run(body, extension, ['analyse', extension], 120, 'application/json')
        elif url.path == '/page' and query.get('number', '').isdigit() and query.get('side', '').isdigit():
            self.run(body, '.pdf', ['page', query['number'], query['side']], 60, 'image/jpeg')
        else:
            self.error(404, 'Route inconnue.')

    def run(self, body: bytes, extension: str, arguments: list, timeout: int, kind: str):
        if not SLOTS.acquire(timeout=90):
            self.error(503, 'Le lecteur de documents est occupé. Réessaie dans un instant.')
            return
        try:
            with tempfile.TemporaryDirectory() as folder:
                path = os.path.join(folder, 'document' + extension)
                with open(path, 'wb') as file:
                    file.write(body)
                arguments.insert(1, path)
                try:
                    done = subprocess.run([sys.executable, str(HERE / 'lecteur.py'), *arguments], capture_output=True, timeout=timeout)
                except subprocess.TimeoutExpired:
                    self.error(422, 'La lecture de ce document a pris trop de temps.')
                    return
        finally:
            SLOTS.release()
        if done.returncode == 0:
            self.reply(200, done.stdout, kind)
        elif done.returncode == 3:
            self.reply(422, done.stdout)
        else:
            detail = (done.stderr.decode(errors='replace').strip().splitlines() or [f'code {done.returncode}'])[-1]
            print(f'lecture échouée : {detail[:300]}', file=sys.stderr, flush=True)
            self.error(422, 'Ce document n’a pas pu être lu.')

    def log_message(self, *args):
        pass


if __name__ == '__main__':
    ThreadingHTTPServer(('0.0.0.0', 8080), Handler).serve_forever()
