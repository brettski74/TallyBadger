#!/bin/sh
# First-time cluster init only (docker-entrypoint-initdb.d).
# Copy the server timezone (from TZ env and/or mounted /etc/localtime) onto the
# application database and role so every connection inherits it by default.
set -eu

tz="$(psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" -Atc "SHOW timezone")"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres <<EOSQL
ALTER DATABASE ${POSTGRES_DB} SET timezone TO '${tz}';
ALTER ROLE ${POSTGRES_USER} SET timezone TO '${tz}';
EOSQL
