from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import base64
from email.parser import BytesParser
from email.policy import HTTP
import json
import struct
import time
import zlib


def png(width, height, color=b'\x80\x60\x40'):
    """Plain PNG of the asked size and color, like an image returned by the image model."""
    def chunk(kind, data):
        return struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    rows = b''.join(b'\x00' + color * width for _ in range(height))
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b''))


def form(content_type, raw):
    """Fields and files of a multipart form, like the image service reads them."""
    message = BytesParser(policy=HTTP).parsebytes(b'Content-Type: ' + content_type.encode() + b'\r\n\r\n' + raw)
    fields, files = {}, {}
    for part in message.iter_parts():
        name = part.get_param('name', header='content-disposition')
        if part.get_filename():
            files[name] = (part.get_content_type(), part.get_payload(decode=True))
        else:
            fields[name] = part.get_payload(decode=True).decode()
    return fields, files


class Mock(BaseHTTPRequestHandler):
    def send_json(self, value):
        payload = json.dumps(value).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def do_POST(self):
        raw = self.rfile.read(int(self.headers['Content-Length']))
        if self.headers.get('Authorization') != 'Bearer integration-test-key':
            self.send_error(401)
            return
        if self.path == '/v1/images/edits':
            # "Transformer": the starting image and a strength, in a multipart form; the new image is green.
            # "Retoucher": no strength, and never style words (they would restyle the image); the new image is blue.
            fields, files = form(self.headers['Content-Type'], raw)
            mime, image = files.get('image', ('', b''))
            retouch = 'strength' not in fields
            ok = fields.get('model') == 'qwen-image-turbo' and fields.get('n') == '1' and fields.get('response_format') == 'b64_json' \
                and fields.get('seed', '').isdigit() and (fields.get('strength') in ('0.625', '0.75', '0.875') or (retouch and 'Style:' not in fields.get('prompt', ''))) \
                and ((mime, image[:4]) == ('image/png', b'\x89PNG') or (mime, image[:3]) == ('image/jpeg', b'\xff\xd8\xff'))
            if not ok or 'image-error' in fields.get('prompt', ''):
                self.send_error(500, 'Private upstream detail: integration-test-key')
                return
            width, height = (int(v) for v in fields['size'].split('x'))
            color = b'\x10\x10\xc0' if retouch else b'\x10\xc0\x10'
            if 'mask' in files:
                # A painted zone: a PNG mask, only with "Retoucher". The new image is purple.
                if not retouch or files['mask'] != ('image/png', files['mask'][1]) or not files['mask'][1].startswith(b'\x89PNG'):
                    self.send_error(500, 'Private upstream detail: integration-test-key')
                    return
                color = b'\x90\x10\xc0'
            self.send_json({'created': 1, 'data': [{'b64_json': base64.b64encode(png(width, height, color)).decode()}]})
            return
        body = json.loads(raw)
        if self.path == '/v1/images/generations':
            # Image model behind LiteLLM: one image per request, its seed chosen by the caller.
            ok = body.get('model') == 'qwen-image-turbo' and body.get('n') == 1 and body.get('response_format') == 'b64_json' \
                and isinstance(body.get('seed'), int) and 'sd_cpp_extra_args' not in body.get('prompt', '')
            if not ok or 'image-error' in body.get('prompt', ''):
                self.send_error(500, 'Private upstream detail: integration-test-key')
                return
            width, height = (int(v) for v in body['size'].split('x'))
            # A style's example drawn with the style's own subject is red: the test sees which subject was used.
            color = b'\xc0\x10\x10' if body['prompt'].startswith('Spider-Man crouching on a rooftop at night\n\nStyle: Spider-Man') else b'\x80\x60\x40'
            payload = json.dumps({'created': 1, 'data': [{'b64_json': base64.b64encode(png(width, height, color)).decode()}]}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        last = body['messages'][-1]['content']
        images = []
        if isinstance(last, list):
            # Mixed message: text parts and images (data URLs sent by the API).
            images = [part['image_url']['url'] for part in last if part.get('type') == 'image_url']
            last = '\n'.join(part['text'] for part in last if part.get('type') == 'text')
        if body.get('tools') and body.get('stream') and not any(m['role'] == 'tool' for m in body['messages']) \
                and ('cherche' in last or isinstance(body.get('tool_choice'), dict)):
            # Qwen calls the search tool: the question, and the depth imposed by the menu when there is one.
            outil = body['tools'][0]['function']
            profondeur = outil['parameters']['properties']['profondeur'].get('enum', ['web'])
            arguments = json.dumps({'question': last, 'profondeur': profondeur[0] if len(profondeur) == 1 else 'web'}, ensure_ascii=False)
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.send_header('Connection', 'close')
            self.end_headers()
            for chunk in ({'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'id': 'appel-1', 'type': 'function', 'function': {'name': outil['name'], 'arguments': ''}}]}}]},
                          {'choices': [{'index': 0, 'delta': {'tool_calls': [{'index': 0, 'function': {'arguments': arguments}}]}}]},
                          {'choices': [{'index': 0, 'delta': {}, 'finish_reason': 'tool_calls'}]},
                          {'choices': [], 'usage': {'prompt_tokens': 1234, 'completion_tokens': 9}}):
                self.wfile.write(('data: ' + json.dumps(chunk, ensure_ascii=False) + '\n\n').encode()); self.wfile.flush()
            self.wfile.write(b'data: [DONE]\n\n'); self.wfile.flush()
            return
        if last == 'upstream-error':
            self.send_error(503, 'Private upstream detail: integration-test-key')
            return
        if body.get('stream') is False:
            # Non-streaming calls: conversation title (formatted like a model would) or summary.
            system = body['messages'][0]['content'] if body['messages'][0]['role'] == 'system' else ''
            content = f'**Titre : Sujet {last}.**' if 'titre' in system else 'Résumé simulé.'
            if 'Qwen-Image' in system:
                # Description of an image rewritten by Qwen, with what the API must clean up.
                assert body.get('reasoning_effort') == 'none'
                content = '<think>Idée</think>\nPrompt: "A detailed red apple on a wooden table."'
                if 'redraws the attached image' in system:
                    # "Image → image": Qwen sees the starting image (its JPEG thumbnail) to describe it.
                    assert len(images) == 1 and images[0].startswith('data:image/jpeg;base64,/9j/')
                    content = 'The same small brown square, as a watercolor painting.'
                if 'edit instruction' in system:
                    # "Retoucher": a short instruction written by Qwen looking at the image.
                    assert len(images) == 1 and images[0].startswith('data:image/jpeg;base64,/9j/')
                    content = '"Make the square blue. Keep everything else exactly the same: the size and the framing."'
            if 'style words' in system:
                # Words of a user's style proposed by Qwen, with what the API must clean up.
                assert body.get('reasoning_effort') == 'none'
                content = '<think>Style</think>\nStyle: "neon glow, synthwave palette, chrome reflections."'
                if 'spiderman' in last.lower():
                    content = 'Spider-Man, comic book art, halftone dots, bold outlines'
            if 'example image of a style' in system:
                # Subject of a style's example: its own when the words name one, the usual fox otherwise.
                assert body.get('reasoning_effort') == 'none'
                content = 'Scene: Spider-Man crouching on a rooftop at night.' if 'Spider-Man' in last else 'DEFAULT'
            if 'SANS recopier' in last:
                # Document page laid out: the first segment is a title, the others one paragraph.
                assert body.get('response_format') == {'type': 'json_object'} and len(images) == 1
                count = last.count('\n[')
                content = json.dumps({'blocs': [{'type': 'titre', 'niveau': 1, 'lignes': [1]},
                                                {'type': 'paragraphe', 'lignes': list(range(2, count + 1))}]})
            elif 'Transcris fidèlement tout le texte de cette page' in last:
                # Scanned page read on its image (a JPEG rendered by doc-guard).
                assert images[0].startswith('data:image/jpeg;base64,/9j/')
                content = 'Courrier lu sur l’image : rendez-vous le treize[?] mai.'
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
        text = json.dumps({'reply': 'Bonjour, été !', 'outils': [t['function']['name'] for t in body.get('tools') or []],
                           'temperature': body['temperature'],
                           'effort': body['reasoning_effort'], 'question': last, 'max_tokens': body['max_tokens'],
                           'images': [url[:40] for url in images]}, ensure_ascii=False)
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
