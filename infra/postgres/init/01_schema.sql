-- Bootstrap: crea lo schema "ad" la prima volta che il volume di Postgres
-- è vuoto. Le tabelle vere vengono poi create dal data_loader (schema.py).
CREATE SCHEMA IF NOT EXISTS ad;
