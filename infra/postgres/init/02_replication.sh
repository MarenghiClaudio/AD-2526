#!/bin/bash
# Crea l'utente di replica e aggiunge il permesso in pg_hba.conf.
# Gira una sola volta, quando il volume è vuoto (docker-entrypoint-initdb.d).
set -e

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    CREATE USER replicator WITH REPLICATION ENCRYPTED PASSWORD 'replicapass';
EOSQL

# Aggiunge la riga di autenticazione per le connessioni di replica.
# Deve venire DOPO la riga "host all all all scram-sha-256" già presente,
# ma postgres legge pg_hba.conf dall'alto verso il basso → append è ok.
echo "host replication replicator all scram-sha-256" >> "${PGDATA}/pg_hba.conf"

# Ricarica la configurazione affinché la nuova riga sia attiva.
pg_ctl reload -D "${PGDATA}"
