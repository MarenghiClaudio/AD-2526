"""
Caricamento dei dati reali da twitter_combined.txt.

Il file contiene coppie "follower_id seguito_id" (una per riga).
Questo modulo estrae gli utenti unici e le relazioni di follow,
poi li inserisce nel DB tramite COPY per massimizzare le prestazioni.
"""

import csv
import io
import random
from datetime import datetime, timedelta

import psycopg2
from faker import Faker

from config import (
    DB_CONFIG,
    DB_SCHEMA,
    POST_WINDOW_DAYS,
    RANDOM_SEED,
    TWITTER_DATA_PATH,
    USER_MEAN_EXTRA_DAYS,
    USER_WINDOW_DAYS,
)


fake = Faker("it_IT")
Faker.seed(RANDOM_SEED)
_rng = random.Random(RANDOM_SEED)


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


def _bulk_copy(cur, table: str, columns: list[str], rows) -> None:
    """
    Inserimento bulk via COPY ... FROM STDIN WITH CSV.

    Il formato CSV gestisce correttamente l'escape di virgolette, virgole,
    newline e backslash nei contenuti, evitando di rompere il parsing.
    """
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    buffer.seek(0)
    cols = ", ".join(columns)
    cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)", buffer)


def _user_created_at(now: datetime) -> str:
    """
    Distribuisce gli iscritti su una finestra storica con bias verso utenti
    più recenti (esponenziale). L'età minima è POST_WINDOW_DAYS, così ogni
    utente esiste prima di qualunque post sintetico — il vincolo logico
    user.created_at <= post.created_at è sempre rispettato.
    """
    age_days = POST_WINDOW_DAYS + _rng.expovariate(1.0 / USER_MEAN_EXTRA_DAYS)
    age_days = min(age_days, USER_WINDOW_DAYS)
    return (now - timedelta(days=age_days)).isoformat()


def load_users_and_follows():
    """
    Pipeline principale:
    1. Legge gli archi dal file
    2. Inserisce gli utenti con username sintetico e created_at distribuito
    3. Inserisce le relazioni di follow
    """
    edges = _read_edges(TWITTER_DATA_PATH)
    user_ids = _extract_users(edges)

    conn = psycopg2.connect(**DB_CONFIG)
    now = datetime.now()

    with conn:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {DB_SCHEMA}")

            # --- Inserimento utenti ---
            print("[loader] Inserimento utenti...")
            user_rows = [
                (uid, f"{fake.user_name()}_{uid}", _user_created_at(now))
                for uid in user_ids
            ]
            _bulk_copy(cur, "users", ["user_id", "username", "created_at"], user_rows)
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
