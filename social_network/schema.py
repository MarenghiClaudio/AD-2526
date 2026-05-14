"""
Creazione dello schema del database.
Definisce le tabelle users, follows, posts e likes
e le ricrea da zero ogni volta che viene eseguito.
"""

import psycopg2
from config import DB_CONFIG, DB_SCHEMA


def build_schema_sql(schema: str) -> str:
    return f"""
SET search_path TO {schema};

-- Elimina le tabelle in ordine inverso rispetto alle dipendenze
DROP TABLE IF EXISTS likes   CASCADE;
DROP TABLE IF EXISTS posts   CASCADE;
DROP TABLE IF EXISTS follows CASCADE;
DROP TABLE IF EXISTS users   CASCADE;

-- Utenti estratti dal dataset Twitter
CREATE TABLE users (
    user_id     BIGINT PRIMARY KEY,
    username    TEXT   NOT NULL,
    created_at  TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Relazioni di follow (chi segue chi)
CREATE TABLE follows (
    follower_id BIGINT NOT NULL REFERENCES users(user_id),
    followed_id BIGINT NOT NULL REFERENCES users(user_id),
    created_at  TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (follower_id, followed_id)
);

-- Post pubblicati dagli utenti
CREATE TABLE posts (
    post_id    BIGSERIAL PRIMARY KEY,
    user_id    BIGINT    NOT NULL REFERENCES users(user_id),
    content    TEXT      NOT NULL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

-- Like ai post (un utente può mettere like a un post una sola volta)
CREATE TABLE likes (
    user_id    BIGINT NOT NULL REFERENCES users(user_id),
    post_id    BIGINT NOT NULL REFERENCES posts(post_id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_id, post_id)
);

-- Indici per i carichi tipici di un social network:
--   * timeline per utente   → posts WHERE user_id=X ORDER BY created_at DESC
--   * feed globale recente  → posts ORDER BY created_at DESC
--   * follower di un utente → follows WHERE followed_id=X
--     (l'inverso, "chi seguo", è già coperto dalla PK di follows)
--   * like di un dato post  → likes WHERE post_id=X
--     (l'inverso, "post a cui ho messo like", è coperto dalla PK di likes)
CREATE INDEX idx_posts_user_created ON posts (user_id, created_at DESC);
CREATE INDEX idx_posts_created      ON posts (created_at DESC);
CREATE INDEX idx_follows_followed   ON follows (followed_id);
CREATE INDEX idx_likes_post         ON likes (post_id);
"""


def create_schema():
    """Connette al DB, imposta il search_path e applica il DDL."""
    print("[schema] Connessione al database...")
    conn = psycopg2.connect(**DB_CONFIG)
    conn.autocommit = True

    with conn.cursor() as cur:
        # Imposta il search_path per la sessione corrente
        cur.execute(f"SET search_path TO {DB_SCHEMA}")
        print(f"[schema] Search path impostato su: {DB_SCHEMA}")

        print("[schema] Creazione delle tabelle...")
        cur.execute(build_schema_sql(DB_SCHEMA))

    conn.close()
    print("[schema] Schema creato con successo.")


if __name__ == "__main__":
    create_schema()
