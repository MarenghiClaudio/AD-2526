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
POSTS_PER_USER    = int(os.getenv("POSTS_PER_USER", 5))
MAX_LIKES_PER_POST = int(os.getenv("MAX_LIKES_PER_POST", 10))
RANDOM_SEED       = int(os.getenv("RANDOM_SEED", 42))
