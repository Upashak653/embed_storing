# ── Imports ────────────────────────────────────────────────────────────────
import os
import time
from itertools import batched  # 💡 DECODE: Python 3.12+ built-in batching

import psycopg2
from pinecone import Pinecone
from dotenv import load_dotenv
from loguru import logger

# ── 🛠️ Internal Helpers ────────────────────────────────────────────────────

load_dotenv()

# 💡 DECODE: Config from .env — no hardcoded secrets
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", 5432),
    "dbname": os.getenv("DB_NAME", "asis"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
}

PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_HOST = os.getenv("PINECONE_HOST")
INDEX_NAME = "qba-api-advisor"
BATCH_SIZE = 100  # Pinecone recommends 100 vectors per upsert


def _fetch_all_embeddings(cur) -> list[tuple]:
    """Fetch id + embedding from local PostgreSQL."""
    logger.info("Fetching all embeddings from PostgreSQL...")
    cur.execute("SELECT id, embedding::float4[] FROM rag.rag_data ORDER BY id")
    rows = cur.fetchall()
    logger.info(f"Fetched {len(rows):,} rows")
    return rows


def _build_pinecone_vectors(rows: list[tuple]) -> list[dict]:
    """Convert postgres rows to Pinecone upsert format."""
    return [
        {
            "id": str(row[0]),        # 💡 DECODE: Pinecone IDs must be strings
            "values": list(row[1]),   # embedding as list of floats
        }
        for row in rows
    ]


# ── 🚀 Public Endpoints ────────────────────────────────────────────────────

def migrate():
    # ── Connect to PostgreSQL
    logger.info("Connecting to PostgreSQL...")
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()

    # ── Connect to Pinecone
    logger.info("Connecting to Pinecone...")
    pc = Pinecone(api_key=PINECONE_API_KEY)
    index = pc.Index(host=PINECONE_HOST)

    # ── Fetch embeddings
    rows = _fetch_all_embeddings(cur)
    vectors = _build_pinecone_vectors(rows)

    # ── Upsert in batches of 100
    total = len(vectors)
    uploaded = 0

    logger.info(f"Starting upsert of {total:,} vectors in batches of {BATCH_SIZE}...")

    for batch in batched(vectors, BATCH_SIZE):
        # 💡 DECODE: batched() splits list into chunks of BATCH_SIZE
        index.upsert(vectors=list(batch))
        uploaded += len(batch)
        logger.info(f"Progress: {uploaded:,}/{total:,} ({(uploaded/total)*100:.1f}%)")
        time.sleep(0.1)  # slight delay to avoid rate limiting

    logger.success(f"✅ Migration complete! {uploaded:,} vectors uploaded to Pinecone.")

    # ── Verify
    stats = index.describe_index_stats()
    logger.info(f"Pinecone index stats: {stats}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    migrate()