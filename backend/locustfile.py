"""
Load generator per i benchmark del backend.

  locust -f locustfile.py --host http://localhost:8000

Modello di carico:
  * mix 95% read / 5% write   (tipico social)
  * accesso skewed sugli user_id via distribuzione Zipf-like
    → senza skew, ogni richiesta picchierebbe utenti diversi e in Fase 2
      la cache non avrebbe mai hot keys da intercettare
  * tre task GET separati per timeline / feed / feed+FoF, così la UI di
    Locust mostra i percentili di ogni endpoint indipendentemente

Pool degli user_id: si carica dal CSV `users.csv` se presente (esportato
da Postgres), altrimenti si usano gli ID interi 1..N — utile per smoke
test ma non rappresentativo. Per i benchmark veri esportare il CSV:

    \\copy (SELECT user_id FROM ad.users) TO 'users.csv' WITH CSV
"""

import csv
import os
import random
from pathlib import Path

from locust import HttpUser, between, task

USERS_CSV = Path(os.getenv("USERS_CSV", "users.csv"))
ZIPF_PARAM = float(os.getenv("ZIPF_PARAM", "1.2"))
USER_POOL_SIZE = int(os.getenv("USER_POOL_SIZE", "10000"))


def _load_user_pool() -> list[int]:
    if USERS_CSV.exists():
        with USERS_CSV.open(newline="", encoding="utf-8") as f:
            reader = csv.reader(f)
            users = [int(row[0]) for row in reader if row]
        if len(users) > USER_POOL_SIZE:
            random.shuffle(users)
            users = users[:USER_POOL_SIZE]
        return users
    # Fallback: smoke test su id contigui (probabilmente NON validi su SNAP)
    return list(range(1, USER_POOL_SIZE + 1))


_USER_POOL = _load_user_pool()


def _zipf_pick(pool: list[int], rng: random.Random) -> int:
    """
    Sampling Zipf-like senza dipendenze esterne.
    Ranghi più bassi (= utenti più "hot") sono picked esponenzialmente
    più spesso. Genera il pattern di accesso che fa emergere hot keys
    in Fase 2.
    """
    n = len(pool)
    rank = int(rng.paretovariate(ZIPF_PARAM)) - 1
    return pool[min(rank, n - 1)]


class BrowsingUser(HttpUser):
    """Utente tipico: legge feed e timeline, occasionalmente mette like."""

    wait_time = between(0.1, 0.3)

    def on_start(self) -> None:
        self.rng = random.Random()

    # --- READ tasks (95% del traffico complessivo) ---

    @task(40)
    def view_feed(self) -> None:
        uid = _zipf_pick(_USER_POOL, self.rng)
        self.client.get(f"/feed/{uid}", name="/feed/{user_id}")

    @task(20)
    def view_feed_fof(self) -> None:
        uid = _zipf_pick(_USER_POOL, self.rng)
        self.client.get(
            f"/feed/{uid}?with_fof=true",
            name="/feed/{user_id}?with_fof=true",
        )

    @task(25)
    def view_timeline(self) -> None:
        uid = _zipf_pick(_USER_POOL, self.rng)
        self.client.get(f"/timeline/{uid}", name="/timeline/{user_id}")

    @task(10)
    def view_profile(self) -> None:
        uid = _zipf_pick(_USER_POOL, self.rng)
        self.client.get(f"/users/{uid}", name="/users/{user_id}")

    # --- WRITE tasks (~5% del traffico complessivo) ---

    @task(3)
    def post_content(self) -> None:
        uid = _zipf_pick(_USER_POOL, self.rng)
        self.client.post(
            "/posts",
            json={"user_id": uid, "content": f"benchmark post {self.rng.random():.6f}"},
            name="/posts",
        )

    @task(2)
    def add_like(self) -> None:
        uid = _zipf_pick(_USER_POOL, self.rng)
        pid = self.rng.randint(1, 200_000)
        # Tolleriamo 404 sul post_id: stiamo solo stressando il path
        with self.client.post(
            "/likes",
            json={"user_id": uid, "post_id": pid},
            name="/likes",
            catch_response=True,
        ) as resp:
            if resp.status_code in (200, 404):
                resp.success()
