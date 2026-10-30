"""Pass account credentials to the API CLI over stdin, never as shell arguments."""
import getpass
import json
from pathlib import Path
import subprocess
import sys

command = 'reset-password' if '--reset' in sys.argv else 'create-user'
username = input('Identifiant : ').strip()
password = getpass.getpass('Mot de passe (12 caractères minimum) : ')
confirm = getpass.getpass('Confirmer le mot de passe : ')
if password != confirm or not 12 <= len(password) <= 256:
    raise SystemExit('Les mots de passe doivent correspondre et contenir entre 12 et 256 caractères.')
result = subprocess.run(['docker', 'compose', 'exec', '-T', 'backend', '/app/observatoire', command],
                        input=json.dumps({'username': username, 'password': password}).encode(),
                        cwd=Path(__file__).resolve().parents[1])
raise SystemExit(result.returncode)
