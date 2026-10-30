"""Create the first account with a random password stored in a local 0600 file."""
from pathlib import Path
import json
import os
import re
import secrets
import subprocess

root = Path(__file__).resolve().parents[1]
command = ['docker', 'compose']
count = subprocess.check_output([*command, 'exec', '-T', 'db', 'psql', '-U', 'observatoire_owner', '-d',
                                 'observatoire', '-Atc', 'SELECT count(*) FROM users'], cwd=root, text=True).strip()
if count != '0':
    print('Un compte existe déjà. Aucun mot de passe modifié.')
    raise SystemExit(0)
target = root / '.initial-admin-password'
if target.is_symlink():
    raise SystemExit('Le fichier de credentials ne doit pas être un lien symbolique.')
if target.exists():
    credentials = json.loads(target.read_text())
else:
    username = 'admin'
    for line in (root/'.env').read_text().splitlines():
        if line.startswith('CHAT_USER='):
            candidate = line.split('=', 1)[1].strip().strip('"\'').lower()
            if re.fullmatch(r'[a-z0-9._@-]{3,64}', candidate): username = candidate
    credentials = {'username': username, 'password': secrets.token_urlsafe(24)}
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as output:
        json.dump(credentials, output, ensure_ascii=False, indent=2)
        output.write('\n')
subprocess.run([*command, 'exec', '-T', 'backend', '/app/observatoire', 'create-user'],
               input=json.dumps(credentials).encode(), cwd=root, check=True)
print('Premier compte créé. Identifiants dans .initial-admin-password (fichier local, exclu de Git).')
