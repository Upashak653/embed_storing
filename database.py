"""Handles schema building, raw embedding extraction via OpenAI, and safe, transaction-scoped database upserts."""

import psycopg2
import requests

from config import (
    DB_CONFIG,
    client,
    EMBEDDING_MODEL,
    ARCADE_BASE,    # ← imported from config, no longer hardcoded here
    ARCADE_AUTH,
    ARCADE_DB,
)


# ── 🚀 ArcadeDB ───────────────────────────────────────────────────────────────

def arcade_cmd(command: str) -> dict:
    """Execute a single ArcadeDB SQL command safely."""
    try:
        res = requests.post(
            f"{ARCADE_BASE}/api/v1/command/{ARCADE_DB}",
            auth=ARCADE_AUTH,
            headers={
                "Content-Type": "application/json",
                "Accept":       "application/json",   # ← required — without this ArcadeDB hangs
            },
            json={"language": "sql", "command": command.strip()},
            timeout=30,
        )
        return res.json()
    except requests.exceptions.Timeout:
        print(f"[ARCADE CMD] Timeout — is ArcadeDB reachable at {ARCADE_BASE}?")
        return {}
    except Exception as e:
        print(f"[ARCADE CMD ERROR] {e}")
        return {}


# ── 🗄️ PostgreSQL ─────────────────────────────────────────────────────────────

def database_setup() -> bool:
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute("CREATE SCHEMA IF NOT EXISTS rag;")
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS rag.rag_data (
                        id            bigserial PRIMARY KEY,
                        chunk_text    TEXT,
                        embedding     vector(1536),
                        search_vector tsvector,
                        source        TEXT,
                        ingested_at   TIMESTAMP DEFAULT now(),
                        CONSTRAINT unique_chunk_text UNIQUE (chunk_text)
                    );
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS rag_data_embedding_hnsw
                    ON rag.rag_data USING hnsw (embedding vector_l2_ops);
                """)
                cur.execute("""
                    CREATE INDEX IF NOT EXISTS rag_data_search_gin
                    ON rag.rag_data USING gin (search_vector);
                """)
                conn.commit()
        print("Database engine components and structural tables verified.")
        return True
    except Exception as e:
        print("Schema verification failure:", e)
        return False


def get_embedding(text: str) -> list[float] | None:
    try:
        if not text or not text.strip():
            print("[EMBED] Empty text — skipping")
            return None
        response = client.embeddings.create(input=text, model=EMBEDDING_MODEL)
        return response.data[0].embedding
    except Exception as e:
        print(f"[EMBED] OpenAI embedding failed: {e}")
        return None


def insert_to_db(cur, chunk_text: str, embedding: list[float], source: str = None) -> bool:
    try:
        cur.execute("""
            INSERT INTO rag.rag_data
                (chunk_text, embedding, search_vector, source, ingested_at)
            VALUES (%s, %s, to_tsvector('english', %s), %s, now())
            ON CONFLICT (chunk_text) DO NOTHING RETURNING id;
        """, (chunk_text, str(embedding), chunk_text, source))

        row = cur.fetchone()
        if row:
            arcade_cmd(f"CREATE VERTEX Chunk SET chunk_id = {row[0]}")
            return True
        return False
    except Exception as e:
        print("Data ingestion insertion failure:", e)
        return False


def clear_database():
    """Wipes all data from PostgreSQL and resets internal ID counters."""
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                print("[RESET] Wiping PostgreSQL table rag.rag_data...")
                cur.execute("TRUNCATE TABLE rag.rag_data RESTART IDENTITY CASCADE;")
                conn.commit()
        print("[RESET] PostgreSQL vector storage is completely empty.")
    except Exception as e:
        print("[RESET] PostgreSQL wipe failure:", e)