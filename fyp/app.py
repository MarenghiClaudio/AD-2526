import os
from typing import Any

import psycopg
from psycopg.rows import dict_row
from flask import Flask, jsonify, render_template, request
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)

DATABASE_URL = os.getenv("DATABASE_URL")
DEFAULT_USER_ID = os.getenv("DEFAULT_USER_ID", "886023")


FYP_QUERY = """
WITH user_likes AS (
    SELECT post_id
    FROM likes
    WHERE user_id = %(user_id)s
),

similar_users AS (
    SELECT l2.user_id, COUNT(*) AS common_likes
    FROM likes l1
    JOIN likes l2 ON l1.post_id = l2.post_id
    WHERE l1.user_id = %(user_id)s
      AND l2.user_id <> %(user_id)s
    GROUP BY l2.user_id
),

post_stats AS (
    SELECT
        p.post_id,
        p.user_id,
        p.content,
        p.created_at,
        COUNT(l.user_id) AS like_count
    FROM posts p
    LEFT JOIN likes l ON p.post_id = l.post_id
    GROUP BY p.post_id, p.user_id, p.content, p.created_at
),

candidate_posts AS (
    SELECT
        ps.*,

        CASE
            WHEN f.followed_id IS NOT NULL THEN 1
            ELSE 0
        END AS from_followed_user,

        COALESCE(SUM(su.common_likes), 0) AS affinity_score,

        EXTRACT(EPOCH FROM (NOW() - ps.created_at)) / 3600 AS age_hours

    FROM post_stats ps

    LEFT JOIN follows f
        ON f.follower_id = %(user_id)s
       AND f.followed_id = ps.user_id

    LEFT JOIN likes l
        ON l.post_id = ps.post_id

    LEFT JOIN similar_users su
        ON su.user_id = l.user_id

    WHERE ps.user_id <> %(user_id)s
      AND ps.post_id NOT IN (SELECT post_id FROM user_likes)
      AND NOT (ps.post_id = ANY(%(excluded_post_ids)s::bigint[]))

    GROUP BY
        ps.post_id,
        ps.user_id,
        ps.content,
        ps.created_at,
        ps.like_count,
        f.followed_id
)

SELECT
    post_id,
    user_id,
    content,
    created_at,
    like_count,
    from_followed_user,
    affinity_score,
    age_hours,

    (
        3.0 * from_followed_user
        + 1.5 * LN(1 + like_count)
        + 2.0 * LN(1 + affinity_score)
        + 4.0 / (1 + age_hours)
        + RANDOM() * 0.2
    ) AS score

FROM candidate_posts
ORDER BY score DESC
LIMIT %(limit)s;
"""


def parse_loaded_ids(value: str | None) -> list[int]:
    if not value:
        return []

    loaded_ids: list[int] = []
    for raw_id in value.split(","):
        raw_id = raw_id.strip()
        if not raw_id:
            continue
        try:
            loaded_ids.append(int(raw_id))
        except ValueError:
            continue

    return loaded_ids


def get_connection():
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL non configurato. Copia .env.example in .env e inserisci la stringa di connessione PostgreSQL.")
    return psycopg.connect(DATABASE_URL, row_factory=dict_row)


def get_recommended_posts(user_id: int, limit: int, excluded_post_ids: list[int] | None) -> list[dict[str, Any]]:
    with get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                FYP_QUERY,
                {
                    "user_id": user_id,
                    "limit": limit,
                    "excluded_post_ids": excluded_post_ids,
                },
            )
            rows = cur.fetchall()

    posts: list[dict[str, Any]] = []
    for row in rows:
        posts.append(
            {
                "post_id": row["post_id"],
                "user_id": row["user_id"],
                "content": row["content"],
                "created_at": row["created_at"].isoformat() if row["created_at"] else None,
                "like_count": int(row["like_count"]),
                "from_followed_user": bool(row["from_followed_user"]),
                "affinity_score": int(row["affinity_score"]),
                "age_hours": float(row["age_hours"]),
                "score": float(row["score"]),
            }
        )

    return posts


@app.route("/")
def index():
    return render_template("index.html", default_user_id=DEFAULT_USER_ID)


@app.route("/api/fyp")
def fyp_api():
    try:
        user_id = int(request.args.get("user_id", DEFAULT_USER_ID))
        limit = int(request.args.get("limit", 20))
        limit = max(1, min(limit, 100))
        excluded_post_ids = parse_loaded_ids(request.args.get("loaded_ids"))

        posts = get_recommended_posts(user_id, limit, excluded_post_ids)
        return jsonify(
            {
                "user_id": user_id,
                "count": len(posts),
                "posts": posts,
            }
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(debug=True, host="127.0.0.1", port=5000)
