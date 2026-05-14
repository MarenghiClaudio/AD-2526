"""
Generazione di dati sintetici: post e like, con distribuzioni realistiche.

Le scelte di distribuzione sono pensate per produrre hot keys credibili, così
che i benchmark del caching layer in Fase 2 mostrino comportamenti asimmetrici
(cache hit ratio non uniforme, eviction policy che fa la differenza, ecc.):

  * post per utente   → Pareto: pochi utenti molto attivi, molti silenti
  * like per post     → Pareto: pochi post virali, molti con 0 like
  * timestamp dei post → esponenziale: bias verso i post recenti
  * candidati al like → solo follower reali dell'autore (Twitter è già
    power-law sui follower, quindi le celebrity ricevono naturalmente
    più like senza bisogno di fallback artificiali).
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
    LIKE_PARETO_ALPHA,
    MAX_LIKES_PER_POST,
    MAX_POSTS_PER_USER,
    POST_MEAN_AGE_DAYS,
    POST_PARETO_ALPHA,
    POST_WINDOW_DAYS,
    RANDOM_SEED,
)


fake = Faker("it_IT")
Faker.seed(RANDOM_SEED)
_rng = random.Random(RANDOM_SEED)


def _bulk_copy(cur, table: str, columns: list[str], rows) -> None:
    """COPY ... FROM STDIN WITH CSV — gestisce escape correttamente."""
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerows(rows)
    buffer.seek(0)
    cols = ", ".join(columns)
    cur.copy_expert(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv)", buffer)


def _fetch_followers_of(cur) -> dict[int, list[int]]:
    """
    Carica le relazioni come dict {followed_id: [follower_id, ...]}.

    A regime questo non è il pattern d'accesso del backend (sarà query
    paginata su Redis/Postgres); qui serve solo a popolare offline il DB.
    """
    print("[generator] Caricamento relazioni di follow...")
    cur.execute("SELECT follower_id, followed_id FROM follows")
    followers_of: dict[int, list[int]] = {}
    for follower, followed in cur.fetchall():
        followers_of.setdefault(followed, []).append(follower)
    return followers_of


def _sample_post_count() -> int:
    """Pareto traslata: int(X-1) genera molti 0 (utenti silenti) e una coda lunga."""
    raw = _rng.paretovariate(POST_PARETO_ALPHA) - 1.0
    return min(int(raw), MAX_POSTS_PER_USER)


def _sample_like_count(max_candidates: int) -> int:
    """Pareto traslata, clampata al numero di candidati e al cap globale."""
    if max_candidates <= 0:
        return 0
    raw = _rng.paretovariate(LIKE_PARETO_ALPHA) - 1.0
    return min(int(raw), MAX_LIKES_PER_POST, max_candidates)


def _random_post_timestamp(now: datetime) -> datetime:
    """Esponenziale: media ~POST_MEAN_AGE_DAYS, troncata a POST_WINDOW_DAYS."""
    age_days = min(_rng.expovariate(1.0 / POST_MEAN_AGE_DAYS), float(POST_WINDOW_DAYS))
    return now - timedelta(days=age_days)


def _generate_posts(user_ids: list[int], now: datetime) -> list[tuple[int, str, str]]:
    """Per ogni utente campiona n_posts power-law, poi genera contenuto + timestamp."""
    print(
        f"[generator] Generazione post (Pareto α={POST_PARETO_ALPHA}, "
        f"cap={MAX_POSTS_PER_USER}, finestra={POST_WINDOW_DAYS}gg)..."
    )
    posts: list[tuple[int, str, str]] = []
    for uid in user_ids:
        for _ in range(_sample_post_count()):
            ts = _random_post_timestamp(now).isoformat()
            posts.append((uid, fake.sentence(nb_words=12), ts))
    print(f"[generator] {len(posts):,} post generati.")
    return posts


def _generate_likes(
    post_records: list[tuple[int, int, datetime]],
    followers_of: dict[int, list[int]],
    now: datetime,
) -> list[tuple[int, int, str]]:
    """
    post_records: lista di (post_id, author_id, post_created_at).

    Per ogni post: campiona like tra i follower reali dell'autore. Il
    timestamp del like è uniforme tra la creazione del post e adesso —
    così rispetta sempre il vincolo logico post.created_at <= like.created_at.
    """
    print(
        f"[generator] Generazione like (Pareto α={LIKE_PARETO_ALPHA}, "
        f"cap={MAX_LIKES_PER_POST})..."
    )
    seen: set[tuple[int, int]] = set()
    likes_with_ts: list[tuple[int, int, str]] = []

    for post_id, author_id, post_ts in post_records:
        candidates = followers_of.get(author_id, ())
        n_likes = _sample_like_count(len(candidates))
        if n_likes == 0:
            continue
        span_seconds = max((now - post_ts).total_seconds(), 0.0)
        for liker_id in _rng.sample(candidates, n_likes):
            if liker_id == author_id:
                continue
            key = (liker_id, post_id)
            if key in seen:
                continue
            seen.add(key)
            like_ts = post_ts + timedelta(seconds=_rng.uniform(0, span_seconds))
            likes_with_ts.append((liker_id, post_id, like_ts.isoformat()))

    print(f"[generator] {len(likes_with_ts):,} like generati.")
    return likes_with_ts


def insert_posts_and_likes(user_ids: list[int]) -> None:
    """
    Pipeline principale:
    1. Genera i post (con timestamp distribuiti) e li inserisce nel DB
    2. Recupera i post_id assegnati dalla sequenza BIGSERIAL
    3. Genera i like (con timestamp coerenti con il post) e li inserisce
    """
    conn = psycopg2.connect(**DB_CONFIG)
    now = datetime.now()

    with conn:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {DB_SCHEMA}")
            followers_of = _fetch_followers_of(cur)

            # --- Post ---
            post_tuples = _generate_posts(user_ids, now)
            print("[generator] Inserimento post nel DB...")
            _bulk_copy(
                cur, "posts", ["user_id", "content", "created_at"], post_tuples
            )

            # Recupera post_id e created_at assegnati dal DB.
            # Non serve ordinare: ogni post viene processato indipendentemente.
            cur.execute("SELECT post_id, user_id, created_at FROM posts")
            post_records = cur.fetchall()

            # --- Like ---
            like_rows = _generate_likes(post_records, followers_of, now)
            print("[generator] Inserimento like nel DB...")
            _bulk_copy(
                cur, "likes", ["user_id", "post_id", "created_at"], like_rows
            )

    conn.close()
    print("[generator] Generazione completata.")


if __name__ == "__main__":
    # Per test standalone: recupera gli user_id dal DB
    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute(f"SET search_path TO {DB_SCHEMA}")
        cur.execute("SELECT user_id FROM users")
        user_ids = [row[0] for row in cur.fetchall()]
    conn.close()
    insert_posts_and_likes(user_ids)
