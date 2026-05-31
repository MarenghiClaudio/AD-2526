#!/bin/sh
# Entrypoint del container replica PostgreSQL.
#
# Al primo avvio (DATA_DIR vuota) esegue pg_basebackup dal primary e
# scrive standby.signal + primary_conninfo nel postgresql.auto.conf
# (flag -R), rendendo il nodo uno standby in streaming replication.
# Agli avvii successivi il volume è già popolato → salta il backup e
# rilancia direttamente postgres.
set -e

DATA_DIR=/var/lib/postgresql/data

if [ ! -f "$DATA_DIR/PG_VERSION" ]; then
    echo "==> Replica: volume vuoto, avvio pg_basebackup dal primary..."
    PGPASSWORD="${REPLICATION_PASSWORD:-replicapass}" pg_basebackup \
        -h "${PRIMARY_HOST:-postgres}" \
        -p "${PRIMARY_PORT:-5432}" \
        -U "${REPLICATION_USER:-replicator}" \
        -D "$DATA_DIR" \
        -P -Xs -R --checkpoint=fast
    echo "==> pg_basebackup completato."
fi

# Avvia postgres come standby (hot_standby=on è il default in PG10+).
exec docker-entrypoint.sh postgres \
    -c max_connections=200 \
    -c shared_buffers=256MB \
    -c work_mem=16MB \
    -c hot_standby=on \
    -c hot_standby_feedback=on
