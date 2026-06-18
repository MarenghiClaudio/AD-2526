#!/usr/bin/env bash
# Eseguito da postgres:16-alpine al primo avvio (initdb).
# Crea l'utente di replica e apre pg_hba.conf alle connessioni remote.
set -e

REPL_PASS="${REPLICATION_PASSWORD:-replpassword}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-SQL
    CREATE ROLE replicator WITH REPLICATION LOGIN PASSWORD '$REPL_PASS';
SQL

# Permette connessioni di streaming replication dai worker/repliche
echo "host  replication  replicator  0.0.0.0/0  md5" >> "$PGDATA/pg_hba.conf"
# Permette connessioni normali (backend VM)
echo "host  all          all         0.0.0.0/0  md5" >> "$PGDATA/pg_hba.conf"

echo "[00_replication] Replication user 'replicator' created."
