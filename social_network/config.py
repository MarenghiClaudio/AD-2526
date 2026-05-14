# Legge la configurazione dal file .env nella stessa directory.
# Modifica .env per cambiare credenziali o parametri senza toccare il codice.

import os
from pathlib import Path
from dotenv import load_dotenv

# Carica il .env dalla directory del progetto
load_dotenv(Path(__file__).parent / ".env")

DB_CONFIG = {
    "host":     os.getenv("DB_HOST", "localhost"),
    "port":     int(os.getenv("DB_PORT", 5432)),
    "dbname":   os.getenv("DB_NAME", "ad"),
    "user":     os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD", ""),
}

DB_SCHEMA         = os.getenv("DB_SCHEMA", "ad")

TWITTER_DATA_PATH = os.getenv("TWITTER_DATA_PATH")
RANDOM_SEED       = int(os.getenv("RANDOM_SEED", 42))

# Finestre temporali per i timestamp sintetici (giorni nel passato).
POST_WINDOW_DAYS     = int(os.getenv("POST_WINDOW_DAYS", 90))
POST_MEAN_AGE_DAYS   = float(os.getenv("POST_MEAN_AGE_DAYS", 15))
USER_WINDOW_DAYS     = int(os.getenv("USER_WINDOW_DAYS", 730))
USER_MEAN_EXTRA_DAYS = float(os.getenv("USER_MEAN_EXTRA_DAYS", 200))

# Distribuzioni power-law (Pareto). Alpha più basso = coda più pesante,
# cioè pochi utenti molto attivi e pochi post virali — pattern realistico
# che genera hot keys per stressare il caching layer.
POST_PARETO_ALPHA  = float(os.getenv("POST_PARETO_ALPHA", 1.3))
LIKE_PARETO_ALPHA  = float(os.getenv("LIKE_PARETO_ALPHA", 1.2))
MAX_POSTS_PER_USER = int(os.getenv("MAX_POSTS_PER_USER", 200))
MAX_LIKES_PER_POST = int(os.getenv("MAX_LIKES_PER_POST", 500))
