"""
Generazione di dati sintetici: post e like.

I post vengono distribuiti uniformemente tra gli utenti.
I like vengono generati con probabilità pesata: chi segue un utente
ha più probabilità di mettere like ai suoi post, simulando traffico reale.
"""

import io
import random
import psycopg2
from faker import Faker
from config import DB_CONFIG, DB_SCHEMA, POSTS_PER_USER, MAX_LIKES_PER_POST, RANDOM_SEED


fake = Faker("it_IT")
Faker.seed(RANDOM_SEED)
random.seed(RANDOM_SEED)


def _bulk_copy(cur, table: str, columns: list[str], rows: list[tuple]) -> None:
    """Inserimento bulk tramite COPY FROM su buffer CSV in memoria."""
    buffer = io.StringIO()
    for row in rows:
        buffer.write("\t".join(str(v) for v in row) + "\n")
    buffer.seek(0)
    cur.copy_from(buffer, table, columns=columns)


def _fetch_follows(cur) -> dict[int, list[int]]:
    """
    Carica le relazioni di follow dal DB.
    Restituisce un dizionario {followed_id: [follower_id, ...]}
    usato per pesare la generazione dei like.
    """
    print("[generator] Caricamento relazioni di follow...")
    cur.execute("SELECT follower_id, followed_id FROM follows")
    followers_of: dict[int, list[int]] = {}
    for follower, followed in cur.fetchall():
        followers_of.setdefault(followed, []).append(follower)
    return followers_of


def generate_posts(user_ids: list[int]) -> list[tuple[int, str]]:
    """
    Genera POSTS_PER_USER post per ogni utente.
    Restituisce lista di tuple (user_id, content).
    """
    print(f"[generator] Generazione post ({POSTS_PER_USER} per utente)...")
    posts = []
    for uid in user_ids:
        for _ in range(POSTS_PER_USER):
            posts.append((uid, fake.sentence(nb_words=12)))
    print(f"[generator] {len(posts):,} post generati.")
    return posts


def generate_likes(
    post_id_user_pairs: list[tuple[int, int]],
    followers_of: dict[int, list[int]],
) -> list[tuple[int, int]]:
    """
    Genera like realistici: per ogni post, campiona tra i follower dell'autore.
    Se l'autore ha pochi follower, aggiunge utenti casuali per raggiungere il minimo.

    Args:
        post_id_user_pairs: lista di (post_id, user_id autore)
        followers_of: dizionario {user_id: [follower_ids]}

    Returns:
        Lista di tuple (user_id, post_id) senza duplicati.
    """
    print("[generator] Generazione like...")
    all_user_ids = list(followers_of.keys()) or list(
        set(uid for _, uid in post_id_user_pairs)
    )
    likes = set()

    for post_id, author_id in post_id_user_pairs:
        # Candidati: prima i follower reali, poi utenti casuali come fallback
        candidates = list(followers_of.get(author_id, []))
        if len(candidates) < MAX_LIKES_PER_POST:
            extra = random.sample(all_user_ids, min(MAX_LIKES_PER_POST, len(all_user_ids)))
            candidates = list(set(candidates + extra))

        # Campiona un numero casuale di like tra 0 e MAX_LIKES_PER_POST
        n_likes = random.randint(0, min(MAX_LIKES_PER_POST, len(candidates)))
        sampled = random.sample(candidates, n_likes)

        for liker_id in sampled:
            # Evita che un utente metta like al proprio post
            if liker_id != author_id:
                likes.add((liker_id, post_id))

    result = list(likes)
    print(f"[generator] {len(result):,} like generati.")
    return result


def insert_posts_and_likes(user_ids: list[int]) -> None:
    """
    Pipeline principale:
    1. Genera i post e li inserisce nel DB
    2. Recupera i post_id assegnati dalla sequenza
    3. Genera i like e li inserisce nel DB
    """
    conn = psycopg2.connect(**DB_CONFIG)

    with conn:
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {DB_SCHEMA}")
            followers_of = _fetch_follows(cur)

            # --- Post ---
            post_tuples = generate_posts(user_ids)
            print("[generator] Inserimento post nel DB...")
            _bulk_copy(cur, "posts", ["user_id", "content"], post_tuples)

            # Recupera i post_id generati dalla sequenza BIGSERIAL
            cur.execute("SELECT post_id, user_id FROM posts")
            post_id_user_pairs = cur.fetchall()

            # --- Like ---
            like_tuples = generate_likes(post_id_user_pairs, followers_of)
            print("[generator] Inserimento like nel DB...")
            _bulk_copy(cur, "likes", ["user_id", "post_id"], like_tuples)

    conn.close()
    print("[generator] Generazione completata.")


if __name__ == "__main__":
    # Per test standalone: recupera gli user_id dal DB
    conn = psycopg2.connect(**DB_CONFIG)
    with conn.cursor() as cur:
        cur.execute("SELECT user_id FROM users")
        user_ids = [row[0] for row in cur.fetchall()]
    conn.close()
    insert_posts_and_likes(user_ids)
