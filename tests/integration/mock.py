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
        if body.get('stream') is False:
            # Non-streaming calls: conversation title (formatted like a model would) or summary.
            system = body['messages'][0]['content'] if body['messages'][0]['role'] == 'system' else ''
            content = f'**Titre : Sujet {last}.**' if 'titre' in system else 'Résumé simulé.'
            payload = json.dumps({'choices': [{'message': {'role': 'assistant', 'content': content}}]}, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/event-stream')
        self.send_header('Connection', 'close')
        self.end_headers()
        text = json.dumps({'reply': 'Bonjour, été !', 'temperature': body['temperature'],
                           'effort': body['reasoning_effort'], 'question': last, 'max_tokens': body['max_tokens']}, ensure_ascii=False)
        if body.get('continue_final_message'):
            # vLLM extends the final assistant message: only accept a well-formed resume.
            resumable = body['messages'][-1]['role'] == 'assistant' and body.get('add_generation_prompt') is False
            text = ' (suite)' if resumable else ' (reprise invalide)'
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
            finish = {'choices': [{'delta': {}, 'finish_reason': 'length' if last == 'longue réponse' else 'stop'}]}
            self.wfile.write(('data: ' + json.dumps(finish) + '\n\n').encode()); self.wfile.flush()
            # Like vLLM with stream_options.include_usage: a last chunk without choices.
            usage = {'choices': [], 'usage': {'prompt_tokens': 1000 + 7*len(body['messages']), 'completion_tokens': len(text)}}
            self.wfile.write(('data: ' + json.dumps(usage) + '\n\n').encode()); self.wfile.flush()
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *args):
        pass


ThreadingHTTPServer(('0.0.0.0', 8080), Mock).serve_forever()
