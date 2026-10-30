"""Write a restricted PostgreSQL dump; does not delete or restore data."""
from datetime import datetime, timezone
from pathlib import Path
import os
import subprocess

root = Path(__file__).resolve().parents[1]
folder = root / 'backups'
folder.mkdir(mode=0o700, exist_ok=True)
name = folder / ('observatoire-' + datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S') + '.dump')
fd = os.open(name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
try:
    with os.fdopen(fd, 'wb') as output:
        subprocess.run(['docker', 'compose', 'exec', '-T', 'db', 'sh', '-c',
                        'PGPASSWORD="$APP_DATABASE_PASSWORD" exec pg_dump -h 127.0.0.1 -U observatoire_app -d observatoire -Fc'],
                       stdout=output, cwd=root, check=True)
except BaseException:
    name.unlink(missing_ok=True)
    raise
print('Sauvegarde créée :', name)
