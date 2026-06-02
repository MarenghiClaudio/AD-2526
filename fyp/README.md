# FYP PostgreSQL - Feed consigliato

Piccola applicazione web per visualizzare i post consigliati da una query FYP su PostgreSQL.

L'applicazione usa la query SQL di ranking basata su:

- autore seguito dall'utente;
- numero di like del post;
- affinità con utenti simili, calcolata tramite like in comune;
- freschezza del post;
- piccola componente random per diversificare il feed.

I post vengono caricati **20 alla volta**. Il frontend mantiene in memoria gli ID dei post già mostrati e li invia al backend. La query li esclude, quindi lo stesso post non viene mostrato due volte nella stessa sessione di caricamento.

## Struttura attesa del database

L'app si aspetta queste tabelle:

```sql
CREATE TABLE users (
    user_id    bigint PRIMARY KEY,
    username   text NOT NULL,
    created_at timestamp DEFAULT now() NOT NULL
);

CREATE TABLE posts (
    post_id    bigserial PRIMARY KEY,
    user_id    bigint NOT NULL REFERENCES users,
    content    text NOT NULL,
    created_at timestamp DEFAULT now() NOT NULL
);

CREATE TABLE follows (
    follower_id bigint NOT NULL REFERENCES users,
    followed_id bigint NOT NULL REFERENCES users,
    created_at  timestamp DEFAULT now() NOT NULL,
    PRIMARY KEY (follower_id, followed_id)
);

CREATE TABLE likes (
    user_id    bigint NOT NULL REFERENCES users,
    post_id    bigint NOT NULL REFERENCES posts,
    created_at timestamp DEFAULT now() NOT NULL,
    PRIMARY KEY (user_id, post_id)
);
```

## Installazione

Crea un ambiente virtuale:

```bash
python -m venv .venv
```

Attivalo su macOS/Linux:

```bash
source .venv/bin/activate
```

Attivalo su Windows PowerShell:

```powershell
.venv\Scripts\Activate.ps1
```

Installa le dipendenze:

```bash
pip install -r requirements.txt
```

## Configurazione

Copia il file di esempio:

```bash
cp .env.example .env
```

Modifica `.env` inserendo la connessione al database:

```env
DATABASE_URL=postgresql://username:password@localhost:5432/nome_database
DEFAULT_USER_ID=886023
```

## Avvio

```bash
python app.py
```

Poi apri nel browser:

```text
http://127.0.0.1:5000
```

## API disponibile

Endpoint:

```text
GET /api/fyp?user_id=886023&limit=20&loaded_ids=1,2,3
```

Parametri:

- `user_id`: utente per cui generare il feed;
- `limit`: massimo 20;
- `loaded_ids`: lista separata da virgole dei post già mostrati, da escludere.

## Indici consigliati

Per rendere la query più veloce sul database popolato:

```sql
CREATE INDEX IF NOT EXISTS idx_posts_user_id ON posts(user_id);
CREATE INDEX IF NOT EXISTS idx_posts_created_at ON posts(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_likes_post_id ON likes(post_id);
CREATE INDEX IF NOT EXISTS idx_likes_user_id ON likes(user_id);
CREATE INDEX IF NOT EXISTS idx_follows_follower_id ON follows(follower_id);
CREATE INDEX IF NOT EXISTS idx_follows_followed_id ON follows(followed_id);
```

## Nota sul funzionamento anti-duplicati

Il backend riceve dal frontend gli ID già caricati. Nella query SQL viene aggiunta questa condizione:

```sql
AND (
    %(excluded_post_ids)s IS NULL
    OR ps.post_id <> ALL(%(excluded_post_ids)s::bigint[])
)
```

Quindi, cliccando su **Carica altri 20 post**, la query ricalcola il ranking ma scarta tutti i post già mostrati.
