"""
Caricamento dei dati reali da twitter_combined.txt.

Il file contiene coppie "follower_id seguito_id" (una per riga).
Questo modulo estrae gli utenti unici e le relazioni di follow,
poi li inserisce nel DB tramite COPY per massimizzare le prestazioni.
"""

import io
import psycopg2
from faker import Faker
from config import DB_CONFIG, DB_SCHEMA, TWITTER_DATA_PATH, RANDOM_SEED


fake = Faker("it_IT")
Faker.seed(RANDOM_SEED)


def _read_edges(path: str) -> list[tuple[int, int]]:
    """Legge il file e restituisce la lista di coppie (follower_id, followed_id)."""
    print(f"[loader] Lettura del file: {path}")
    edges = []
    with open(path, "r") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) == 2:
                edges.append((int(parts[0]), int(parts[1])))
    print(f"[loader] Letti {len(edges):,} archi.")
    return edges


def _extract_users(edges: list[tuple[int, int]]) -> set[int]:
    """Estrae l'insieme degli user_id unici da tutte le coppie."""
    user_ids = set()
    for follower, followed in edges:
        user_ids.add(follower)
        user_ids.add(followed)
    print(f"[loader] Trovati {len(user_ids):,} utenti unici.")
    return user_ids


def _bulk_copy(cur, table: str, columns: list[str], rows: list[tuple]) -> None:
    """
    Inserisce righe nel DB tramite COPY FROM (molto più veloce di INSERT).
    Serializza le righe in un buffer CSV in memoria.
    """
    buffer = io.StringIO()
    for row in rows:
        buffer.write("\t".join(str(v) for v in row) + "\n")
    buffer.seek(0)
    cur.copy_from(buffer, table, columns=columns)


def load_users_and_follows():
    """
    Pipeline principale:
    1. Legge gli archi dal file
    2. Inserisce gli utenti con username sintetico
    3. Inserisce le relazioni di follow
    """
    edges = _read_edges(TWITTER_DATA_PATH)
    user_ids = _extract_users(edges)

    conn = psycopg2.connect(**DB_CONFIG)

    with conn:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {DB_SCHEMA}")

            # --- Inserimento utenti ---
            print("[loader] Inserimento utenti...")
            user_rows = [
                (uid, fake.user_name() + f"_{uid}")
                for uid in user_ids
            ]
            _bulk_copy(cur, "users", ["user_id", "username"], user_rows)
            print(f"[loader] {len(user_rows):,} utenti inseriti.")

            # --- Inserimento follow ---
            # Filtra auto-riferimenti e duplicati presenti nel dataset
            print("[loader] Inserimento relazioni di follow...")
            follow_rows = list({
                (follower, followed)
                for follower, followed in edges
                if follower != followed
            })
            _bulk_copy(cur, "follows", ["follower_id", "followed_id"], follow_rows)
            print(f"[loader] {len(follow_rows):,} relazioni di follow inserite.")

    conn.close()
    print("[loader] Caricamento completato.")

    # Restituisce gli user_id per uso nei moduli successivi
    return list(user_ids)


if __name__ == "__main__":
    load_users_and_follows()
