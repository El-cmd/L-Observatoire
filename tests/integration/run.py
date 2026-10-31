"""Security and persistence checks on a disposable, isolated Docker Compose project.

Only this project's test volume is removed. No access to the application's .env.
"""
from http.cookiejar import CookieJar
import json
import os
from pathlib import Path
import secrets
import socket
import struct
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
import zlib

ROOT = Path(__file__).resolve().parents[2]
PROJECT = 'observatoire-test-' + secrets.token_hex(4)
TEMP = tempfile.TemporaryDirectory(prefix='observatoire-integration-')
with socket.socket() as sock:
    sock.bind(('127.0.0.1', 0))
    PORT = sock.getsockname()[1]
ORIGIN = 'http://localhost:' + str(PORT)
config = Path(TEMP.name) / '.env'
config.write_text(f'TEST_PORT={PORT}\nPOSTGRES_PASSWORD={secrets.token_hex(24)}\nPOSTGRES_ADMIN_PASSWORD={secrets.token_hex(24)}\n')
config.chmod(0o600)
BASE = ['docker', 'compose', '-p', PROJECT, '--env-file', str(config), '-f', str(ROOT/'compose.yaml'), '-f', str(ROOT/'tests/integration/compose.yaml')]
PASSWORD = 'Integration-test-password-2026!'


def compose(*args, **kwargs):
    return subprocess.run([*BASE, *args], cwd=ROOT, check=True, **kwargs)


def sql(query, database='observatoire', admin=False):
    command = ['exec', '-T', 'db', 'psql', '-v', 'ON_ERROR_STOP=1', '-U', 'observatoire_owner' if admin else 'observatoire_app', '-d', database, '-Atc', query]
    return compose(*command, capture_output=True, text=True).stdout.strip()


def wait_ready():
    deadline = time.monotonic() + 100
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(ORIGIN+'/api/health', timeout=3) as response:
                if response.status == 200: return
        except (OSError, urllib.error.URLError):
            time.sleep(0.5)
    raise RuntimeError('Test services did not become ready')


class Client:
    def __init__(self):
        self.cookies = CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.csrf = ''

    def call(self, path, method='GET', body=None, csrf=True, origin=ORIGIN, stream=False):
        headers = {'Origin': origin}
        if body is not None: headers['Content-Type'] = 'application/json'
        if csrf and self.csrf: headers['X-CSRF-Token'] = self.csrf
        request = urllib.request.Request(ORIGIN+path, data=json.dumps(body).encode() if body is not None else None, method=method, headers=headers)
        try: response = self.opener.open(request, timeout=20)
        except urllib.error.HTTPError as error: response = error
        if stream: return response
        with response:
            raw = response.read()
            try: data = json.loads(raw) if raw else None
            except ValueError: data = raw.decode()
            return response.status, data, response.headers

    def login(self, username='alice', password=PASSWORD):
        code, result, headers = self.call('/api/auth/login', 'POST', {'username': username, 'password': password})
        if code != 200: raise AssertionError(f'Login failed: HTTP {code}: {result}')
        self.csrf = result['csrf_token']
        return result, headers

    def create(self, question='Bonjour'):
        code, chat, _ = self.call('/api/conversations', 'POST')
        assert code == 201, (code, chat)
        code, chat, _ = self.call('/api/conversations/'+chat['id'], 'PUT', {'version': chat['version'], 'messages': [{'role': 'user', 'content': question}]})
        assert code == 200, (code, chat)
        return chat


def png(width=40, height=30, extra=b''):
    rows = b''.join(b'\x00' + bytes((x * 5 + y) % 256 for x in range(width) for _ in range(3)) for y in range(height))
    chunk = lambda kind, data: struct.pack('>I', len(data)) + kind + data + struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    return (b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('>IIBBBBB', width, height, 8, 2, 0, 0, 0))
            + chunk(b'IDAT', zlib.compress(rows)) + chunk(b'IEND', b'') + extra)


def upload(client, data, name='capture.png'):
    request = urllib.request.Request(ORIGIN + '/api/attachments?name=' + urllib.parse.quote(name), data=data, method='POST',
                                     headers={'Origin': ORIGIN, 'Content-Type': 'application/octet-stream', 'X-CSRF-Token': client.csrf})
    try: response = client.opener.open(request, timeout=60)
    except urllib.error.HTTPError as error: response = error
    with response: return response.status, json.loads(response.read() or b'null')


class Integration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        for name in ('alice', 'bob'):
            compose('exec', '-T', 'backend', '/app/observatoire', 'create-user', input=json.dumps({'username': name, 'password': PASSWORD}).encode(), stdout=subprocess.DEVNULL)
        cls.alice = Client(); cls.alice.login()
        cls.bob = Client(); cls.bob.login('bob')

    def test_01_anonymous_requests_are_rejected(self):
        client = Client()
        self.assertEqual(client.call('/api/conversations')[0], 401)
        self.assertEqual(client.call('/api/conversations', 'POST')[0], 401)
        self.assertEqual(client.call('/api/auth/register', 'POST', {})[0], 404)

    def test_02_cookies_hashes_and_database_privileges(self):
        client = Client(); _, headers = client.login()
        cookie = headers['Set-Cookie']
        self.assertIn('HttpOnly', cookie); self.assertIn('SameSite=Lax', cookie)
        self.assertNotIn('Secure', cookie)  # HTTP localhost; HTTPS enables Secure automatically.
        self.assertEqual(sql("SELECT rolsuper FROM pg_roles WHERE rolname=current_user"), 'f')
        self.assertTrue(sql("SELECT password_hash FROM users WHERE username='alice'").startswith('$argon2id$'))
        token = next(iter(client.cookies)).value
        self.assertEqual(sql("SELECT count(*) FROM sessions WHERE token_hash='"+token+"'"), '0')

    def test_03_origin_and_csrf_are_required(self):
        self.assertEqual(self.alice.call('/api/conversations', 'POST', csrf=False)[0], 403)
        self.assertEqual(self.alice.call('/api/conversations', 'POST', origin='https://evil.example')[0], 403)
        self.assertEqual(Client().call('/api/auth/login', 'POST', {'username': 'alice', 'password': PASSWORD}, origin='https://evil.example')[0], 403)

    def test_04_conversations_are_owned_and_versioned(self):
        chat = self.alice.create(); path = '/api/conversations/'+chat['id']
        for method, body in [('GET', None), ('DELETE', None), ('PUT', {'version': chat['version'], 'messages': []})]:
            self.assertEqual(self.bob.call(path, method, body)[0], 404)
        self.assertEqual(self.bob.call(path+'/generate', 'POST', {'version':chat['version']})[0], 404)
        self.assertEqual(self.alice.call(path, 'PUT', {'version': 0, 'messages': []})[0], 409)
        self.assertEqual(self.alice.call(path)[1]['messages'][0]['content'], 'Bonjour')

    def test_05_streaming_is_persisted_and_parameters_are_forwarded(self):
        chat = self.alice.create('question été'); path = '/api/conversations/'+chat['id']
        with self.alice.call(path+'/generate', 'POST', {'version':chat['version'], 'temperature':1.2, 'reasoning_effort':'xhigh'}, stream=True) as response:
            self.assertEqual(response.status, 200); raw = response.read().decode()
            self.assertIn('data: [DONE]', raw)
        saved = self.alice.call(path)[1]
        self.assertGreater(saved['version'], chat['version'])
        self.assertEqual(saved['title'], 'Sujet question été')
        reply = json.loads(saved['messages'][-1]['content'])
        self.assertEqual(reply['temperature'], 1.2); self.assertEqual(reply['effort'], 'xhigh'); self.assertEqual(reply['question'], 'question été')
        other_browser = Client(); other_browser.login()
        self.assertEqual(other_browser.call(path)[1]['messages'], saved['messages'])

    def test_05b_context_starts_from_qwen_prompt_count(self):
        chat = self.alice.create('combien de tokens ?'); path = '/api/conversations/'+chat['id']
        with self.alice.call(path+'/generate', 'POST', {'version':chat['version']}, stream=True) as response:
            self.assertIn('data: [DONE]', response.read().decode())
        usage = self.alice.call(path+'/context')[1]
        self.assertEqual(usage['measured_tokens'], 1007)
        self.assertGreater(usage['used_tokens'], 1007)
        self.assertIn('Qwen', usage['source'])
        self.assertLess(usage['safety_tokens'], 15_720)
        saved = self.alice.call(path)[1]
        edited = [{'role': 'user', 'content': 'autre question'}] + saved['messages'][1:]
        self.assertEqual(self.alice.call(path, 'PUT', {'version': saved['version'], 'messages': edited})[0], 200)
        self.assertEqual(self.alice.call(path+'/context')[1]['measured_tokens'], 0)

    def test_05c_answers_get_the_room_left_and_can_be_resumed(self):
        chat = self.alice.create('longue réponse'); path = '/api/conversations/'+chat['id']
        self.assertEqual(self.alice.call(path+'/generate', 'POST', {'version':chat['version'], 'continue':True})[0], 400)
        with self.alice.call(path+'/generate', 'POST', {'version':chat['version']}, stream=True) as response:
            self.assertIn('data: [DONE]', response.read().decode())
        saved = self.alice.call(path)[1]; first = saved['messages'][-1]['content']
        self.assertEqual(json.loads(first)['max_tokens'], 32768)
        self.assertTrue(saved['messages'][-1]['truncated'])
        self.assertEqual(self.alice.call(path+'/context')[1]['max_output_tokens'], 32768)
        with self.alice.call(path+'/generate', 'POST', {'version':saved['version'], 'continue':True}, stream=True) as response:
            self.assertIn('data: [DONE]', response.read().decode())
        resumed = self.alice.call(path)[1]
        self.assertEqual(len(resumed['messages']), len(saved['messages']))
        self.assertEqual(resumed['messages'][-1]['content'], first + ' (suite)')
        self.assertNotIn('truncated', resumed['messages'][-1])

    def test_05d_six_conversations_can_stream_at_once(self):
        chats = [self.alice.create('slow') for _ in range(7)]
        streams = [self.alice.call('/api/conversations/'+chat['id']+'/generate', 'POST', {'version':chat['version']}, stream=True) for chat in chats[:6]]
        try:
            self.assertEqual([stream.status for stream in streams], [200]*6)
            code, body, _ = self.alice.call('/api/conversations/'+chats[6]['id']+'/generate', 'POST', {'version':chats[6]['version']})
            self.assertEqual(code, 429); self.assertIn('six', body['error'])
        finally:
            for stream in streams:
                with stream: stream.read()

    def test_05e_renamed_titles_are_kept(self):
        chat = self.alice.create('à renommer'); path = '/api/conversations/'+chat['id']
        self.assertEqual(self.alice.call(path+'/title', 'PUT', {'title': '  \n '})[0], 400)
        self.assertEqual(self.bob.call(path+'/title', 'PUT', {'title': 'Intrus'})[0], 404)
        code, renamed, _ = self.alice.call(path+'/title', 'PUT', {'title': ' Mon titre '})
        self.assertEqual((code, renamed['title']), (200, 'Mon titre'))
        with self.alice.call(path+'/generate', 'POST', {'version':chat['version']}, stream=True) as response:
            self.assertIn('data: [DONE]', response.read().decode())
        saved = self.alice.call(path)[1]; self.assertEqual(saved['title'], 'Mon titre')
        edited = saved['messages'] + [{'role': 'user', 'content': 'suite'}]
        self.assertEqual(self.alice.call(path, 'PUT', {'version': saved['version'], 'messages': edited})[1]['title'], 'Mon titre')
        listed = {item['id']: item['title'] for item in self.alice.call('/api/conversations')[1]}
        self.assertEqual(listed[chat['id']], 'Mon titre')

    def test_05f_images_live_in_the_library_and_reach_qwen(self):
        code, image = upload(self.alice, png(extra=b'<script>alert(1)</script>'))
        self.assertEqual(code, 201, image); self.assertEqual((image['width'], image['height'], image['name']), (40, 30, 'capture.png'))
        self.assertEqual(upload(self.alice, png(extra=b'<script>alert(1)</script>'))[1]['id'], image['id'])
        self.assertEqual(upload(self.alice, b'%PDF-1.7 pas une image')[0], 400)
        raw = self.alice.opener.open(ORIGIN + '/api/attachments/' + image['id'], timeout=20)
        body = raw.read(); etag = raw.headers['ETag']
        self.assertTrue(body.startswith(b'\x89PNG')); self.assertNotIn(b'<script>', body)
        self.assertEqual(raw.headers['Content-Type'], 'image/png'); self.assertIn('sandbox', raw.headers['Content-Security-Policy'])
        cached = urllib.request.Request(ORIGIN + '/api/attachments/' + image['id'], headers={'If-None-Match': etag})
        with self.assertRaises(urllib.error.HTTPError) as unchanged: self.alice.opener.open(cached, timeout=20)
        self.assertEqual(unchanged.exception.code, 304)
        self.assertTrue(self.alice.opener.open(ORIGIN + '/api/attachments/' + image['id'] + '/thumbnail', timeout=20).read().startswith(b'\xff\xd8'))
        self.assertEqual(self.bob.call('/api/attachments/' + image['id'])[0], 404)
        self.assertEqual(self.bob.call('/api/attachments')[1]['items'], [])
        listed = self.alice.call('/api/attachments')[1]
        self.assertIn(image['id'], [item['id'] for item in listed['items']]); self.assertGreater(listed['used_bytes'], 0)
        # A message showing the image: Qwen receives the clean image, the conversation is listed.
        chat = self.alice.call('/api/conversations', 'POST')[1]; path = '/api/conversations/' + chat['id']
        ref = {key: image[key] for key in ('id', 'name', 'width', 'height')}
        _, bob_image = upload(self.bob, png(8, 8))
        foreign = {'id': bob_image['id'], 'name': 'x.png', 'width': 8, 'height': 8}
        self.assertEqual(self.alice.call(path, 'PUT', {'version': chat['version'], 'messages': [{'role': 'user', 'content': '', 'attachments': [foreign]}]})[0], 400)
        code, chat, _ = self.alice.call(path, 'PUT', {'version': chat['version'], 'messages': [{'role': 'user', 'content': 'Que vois-tu ?', 'attachments': [ref]}]})
        self.assertEqual(code, 200, chat)
        usage = self.alice.call(path + '/context')[1]; self.assertGreaterEqual(usage['used_tokens'], 66)
        with self.alice.call(path + '/generate', 'POST', {'version': chat['version']}, stream=True) as response:
            self.assertIn('data: [DONE]', response.read().decode())
        saved = self.alice.call(path)[1]; reply = json.loads(saved['messages'][-1]['content'])
        self.assertEqual(len(reply['images']), 1); self.assertTrue(reply['images'][0].startswith('data:image/png;base64,iVBORw0KGgo'))
        self.assertEqual(saved['messages'][0]['attachments'], [ref])
        self.assertEqual(self.alice.call('/api/attachments/' + image['id'] + '/conversations')[1][0]['id'], chat['id'])
        # Asking again about the same image does not send it twice.
        again = self.alice.call(path, 'PUT', {'version': saved['version'], 'messages': saved['messages'] + [{'role': 'user', 'content': 'Et la couleur ?', 'attachments': [ref]}]})[1]
        with self.alice.call(path + '/generate', 'POST', {'version': again['version']}, stream=True) as response: response.read()
        repeated = json.loads(self.alice.call(path)[1]['messages'][-1]['content'])
        self.assertEqual(repeated['images'], []); self.assertIn('montrée plus haut', repeated['question'])
        saved = self.alice.call(path)[1]
        # Deleting the image leaves a mention for Qwen; deleting a conversation keeps its images.
        self.assertEqual(self.alice.call('/api/attachments/' + image['id'], 'DELETE')[0], 204)
        regenerate = {'version': saved['version'], 'messages': saved['messages'][:1]}
        chat = self.alice.call(path, 'PUT', regenerate)[1]
        with self.alice.call(path + '/generate', 'POST', {'version': chat['version']}, stream=True) as response: response.read()
        reply = json.loads(self.alice.call(path)[1]['messages'][-1]['content'])
        self.assertEqual(reply['images'], []); self.assertIn('[image supprimée : capture.png]', reply['question'])
        _, kept = upload(self.alice, png(12, 12), 'gardée.png')
        other = self.alice.call('/api/conversations', 'POST')[1]
        self.alice.call('/api/conversations/' + other['id'], 'PUT', {'version': other['version'], 'messages': [{'role': 'user', 'content': '', 'attachments': [{key: kept[key] for key in ('id', 'name', 'width', 'height')}]}]})
        self.assertEqual(self.alice.call('/api/conversations/' + other['id'], 'DELETE')[0], 204)
        self.assertIn(kept['id'], [item['id'] for item in self.alice.call('/api/attachments')[1]['items']])

    def test_05g_images_are_transcribed_only_when_summarized(self):
        _, image = upload(self.alice, png(24, 24), 'tableau.png')
        ref = {key: image[key] for key in ('id', 'name', 'width', 'height')}
        chat = self.alice.call('/api/conversations', 'POST')[1]; path = '/api/conversations/' + chat['id']
        messages = [{'role': 'user', 'content': 'Lis ce tableau', 'attachments': [ref]}, {'role': 'assistant', 'content': 'Lu.'},
                    {'role': 'user', 'content': 'Et ensuite ?'}, {'role': 'assistant', 'content': 'Suite.'},
                    {'role': 'user', 'content': 'Dernière question'}, {'role': 'assistant', 'content': 'Fin.'}]
        chat = self.alice.call(path, 'PUT', {'version': chat['version'], 'messages': messages})[1]
        self.assertEqual(sql(f"SELECT coalesce(transcript, 'aucune') FROM attachments WHERE id='{image['id']}'"), 'aucune')
        code, compacted, _ = self.alice.call(path + '/compact', 'POST', {'version': chat['version']})
        self.assertEqual(code, 200, compacted); self.assertEqual(compacted['context_summary'], 'Résumé simulé.')
        self.assertEqual(sql(f"SELECT transcript FROM attachments WHERE id='{image['id']}'"), 'Résumé simulé.')
        self.assertEqual(compacted['messages'][0]['attachments'], [ref])

    def test_06_upstream_errors_release_the_generation_lease(self):
        chat = self.alice.create('upstream-error'); path = '/api/conversations/'+chat['id']
        code, result, _ = self.alice.call(path+'/generate', 'POST', {'version':chat['version']})
        self.assertEqual(code, 502); self.assertNotIn('integration-test-key', json.dumps(result))
        self.assertEqual(self.alice.call(path, 'PUT', {'version':chat['version'], 'messages':[{'role':'user','content':'Retry'}]})[0], 200)

    def test_07_cancel_preserves_partial_response_and_releases_lock(self):
        chat = self.alice.create('slow'); path = '/api/conversations/'+chat['id']
        response = self.alice.call(path+'/generate', 'POST', {'version':chat['version']}, stream=True)
        self.assertEqual(response.status,200); self.assertTrue(response.readline()); response.close()
        saved = None
        for _ in range(40):
            saved = self.alice.call(path)[1]
            if saved['version'] > chat['version']: break
            time.sleep(0.1)
        self.assertGreater(saved['version'],chat['version'])
        self.assertTrue(saved['messages'][-1]['interrupted'])
        self.assertEqual(self.alice.call(path,'PUT',{'version':saved['version'],'messages':[{'role':'user','content':'After stop'}]})[0],200)

    def test_08_session_rotation_logout_and_expiration(self):
        client = Client(); client.login(); old_cookie = next(iter(client.cookies)).value
        client.login(); new_cookie = next(iter(client.cookies)).value; self.assertNotEqual(old_cookie,new_cookie)
        replay = Client(); request = urllib.request.Request(ORIGIN+'/api/auth/me',headers={'Cookie':'observatoire_session='+old_cookie})
        with self.assertRaises(urllib.error.HTTPError) as error: replay.opener.open(request)
        self.assertEqual(error.exception.code,401)
        self.assertEqual(client.call('/api/auth/logout','POST')[0],204)
        self.assertEqual(client.call('/api/auth/me')[0],401)
        expired = Client(); expired.login('bob')
        token = next(iter(expired.cookies)).value
        import hashlib
        sql("UPDATE sessions SET expires_at=now()-interval '1 second' WHERE token_hash='"+hashlib.sha256(token.encode()).hexdigest()+"'",admin=True)
        self.assertEqual(expired.call('/api/auth/me')[0],401)

    def test_09_password_change_revokes_all_sessions(self):
        first=Client();first.login('bob');second=Client();second.login('bob')
        self.assertEqual(first.call('/api/auth/password','PUT',{'current_password':'wrong','new_password':'New-integration-password-2026!'})[0],401)
        self.assertEqual(first.call('/api/auth/me')[0],200)
        self.assertEqual(first.call('/api/auth/password','PUT',{'current_password':PASSWORD,'new_password':'short'})[0],400)
        self.assertEqual(first.call('/api/auth/password','PUT',{'current_password':PASSWORD,'new_password':'New-integration-password-2026!'})[0],204)
        self.assertEqual(second.call('/api/auth/me')[0],401)
        self.assertEqual(Client().call('/api/auth/login','POST',{'username':'bob','password':PASSWORD})[0],401)
        Client().login('bob','New-integration-password-2026!')

    def test_10_rate_limit_blocks_repeated_failures(self):
        client=Client();codes=[]
        for _ in range(9):codes.append(client.call('/api/auth/login','POST',{'username':'does-not-exist','password':'wrong-password'})[0])
        self.assertIn(429,codes)

    def test_11_history_and_sessions_survive_api_restart(self):
        chat=self.alice.create('Persist across restart')
        compose('restart','backend',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        wait_ready()
        self.assertEqual(self.alice.call('/api/auth/me')[0],200)
        self.assertEqual(self.alice.call('/api/conversations/'+chat['id'])[1]['messages'][0]['content'],'Persist across restart')

    def test_12_backup_can_be_restored(self):
        dump=compose('exec','-T','db','pg_dump','-U','observatoire_app','-d','observatoire','-Fc',capture_output=True).stdout
        self.assertGreater(len(dump),1000)
        sql('CREATE DATABASE restore_check',admin=True)
        compose('exec','-T','db','pg_restore','--no-owner','--no-privileges','-U','observatoire_owner','-d','restore_check',input=dump,stdout=subprocess.DEVNULL)
        self.assertEqual(sql('SELECT count(*) FROM conversations',database='restore_check',admin=True),sql('SELECT count(*) FROM conversations'))

    def test_11b_restart_during_stream_preserves_partial_answer(self):
        chat=self.alice.create('slow');path='/api/conversations/'+chat['id']
        response=self.alice.call(path+'/generate','POST',{'version':chat['version']},stream=True)
        self.assertTrue(response.readline())
        compose('restart','backend',stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        response.close();wait_ready()
        saved=self.alice.call(path)[1]
        self.assertGreater(saved['version'],chat['version'])
        self.assertTrue(saved['messages'][-1]['interrupted'])
        self.assertEqual(self.alice.call(path,'PUT',{'version':saved['version'],'messages':[{'role':'user','content':'After restart'}]})[0],200)


if __name__=='__main__':
    success=False
    try:
        compose('up','-d','--no-build',stdout=subprocess.DEVNULL)
        wait_ready()
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(Integration)
        success=unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful()
        if success and os.getenv('OBSERVATOIRE_BROWSER') == '1':
            environment = dict(os.environ, TEST_BASE_URL=ORIGIN)
            subprocess.run([os.getenv('BROWSER_RUNNER', 'node'), str(ROOT/'tests/browser.mjs')], env=environment, check=True, cwd=ROOT)
    finally:
        compose('down','-v','--remove-orphans',stdout=subprocess.DEVNULL)
        TEMP.cleanup()
    raise SystemExit(0 if success else 1)
