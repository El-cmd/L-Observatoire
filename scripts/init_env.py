"""Create local configuration without overwriting existing values or printing secrets."""
from pathlib import Path
import os
import secrets

root = Path(__file__).resolve().parents[1]
target = root / '.env'
if not target.exists():
    target.touch(mode=0o600)
    target.write_text((root / '.env.example').read_text())
text = target.read_text()
values = {}
for line in text.splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        values[key] = value.strip().strip('"\'')
additions = []
for key in ('POSTGRES_ADMIN_PASSWORD', 'POSTGRES_PASSWORD'):
    if not values.get(key):
        # URL-safe alphabet; valid both in Compose env files and in DATABASE_URL.
        value = secrets.token_hex(32)
        text = '\n'.join(line for line in text.splitlines() if not line.startswith(key + '='))
        additions.append(key + '=' + value)
if not values.get('PUBLIC_ORIGIN'):
    text = '\n'.join(line for line in text.splitlines() if not line.startswith('PUBLIC_ORIGIN='))
    additions.append('PUBLIC_ORIGIN=http://localhost:' + values.get('PORT', '8080'))
if additions:
    target.write_text(text.rstrip() + '\n' + '\n'.join(additions) + '\n')
os.chmod(target, 0o600)
print('Configuration locale prête. Secrets PostgreSQL générés si nécessaire.')
