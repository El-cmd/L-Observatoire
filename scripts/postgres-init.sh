#!/bin/sh
set -eu
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -v app_password="$APP_DATABASE_PASSWORD" <<'SQL'
CREATE ROLE observatoire_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION PASSWORD :'app_password';
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
ALTER SCHEMA public OWNER TO observatoire_app;
GRANT CONNECT ON DATABASE observatoire TO observatoire_app;
GRANT USAGE, CREATE ON SCHEMA public TO observatoire_app;
SQL
