from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import time


class Mock(BaseHTTPRequestHandler):
    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        if self.headers.get('Authorization') != 'Bearer integration-test-key':
            self.send_error(401)
            return
        last = body['messages'][-1]['content']
        if last == 'upstream-error':
            self.send_error(503, 'Private upstream detail: integration-test-key')
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()
        text = json.dumps({'reply': 'Bonjour, été !', 'temperature': body['temperature'],
                           'effort': body['reasoning_effort'], 'question': last}, ensure_ascii=False)
        if last == 'slow':
            text = 'Réponse lente. ' * 30
        try:
            for index in range(0, len(text), 5):
                event = 'data: ' + json.dumps({'choices': [{'delta': {'content': text[index:index+5]}}]}, ensure_ascii=False) + '\n\n'
                # Split the HTTP writes, including possible multibyte UTF-8 characters.
                encoded = event.encode()
                self.wfile.write(encoded[:17]); self.wfile.flush()
                self.wfile.write(encoded[17:]); self.wfile.flush()
                if last == 'slow': time.sleep(0.06)
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


ThreadingHTTPServer(('0.0.0.0', 8080), Mock).serve_forever()
