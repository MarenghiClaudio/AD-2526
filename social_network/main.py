"""
Entry point del progetto.

Esegue in sequenza:
  1. Creazione dello schema (DROP + CREATE tabelle)
  2. Caricamento utenti e follow dal dataset Twitter
  3. Generazione e inserimento di post e like sintetici
"""

import time
from schema import create_schema
from loader import load_users_and_follows
from generator import insert_posts_and_likes


def main():
    start = time.time()

    print("=== FASE 1: Creazione schema ===")
    create_schema()

    print("\n=== FASE 2: Caricamento utenti e follow ===")
    user_ids = load_users_and_follows()

    print("\n=== FASE 3: Generazione post e like ===")
    insert_posts_and_likes(user_ids)

    elapsed = time.time() - start
    print(f"\nImportazione completata in {elapsed:.1f} secondi.")


if __name__ == "__main__":
    main()
