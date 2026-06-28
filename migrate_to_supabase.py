# ── Imports ────────────────────────────────────────────────────────────────
import os
import csv
import time

import psycopg2
from dotenv import load_dotenv
from loguru import logger

# ── 🛠️ Internal Helpers ────────────────────────────────────────────────────

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_DB_URL")  # session pooler connection string
BATCH_SIZE = 500

RAG_DATA_CSV = r"C:\Users\QBA SAP\rag_data_no_embeddings.csv"
USERS_CSV = r"C:\Users\QBA SAP\rag_users.csv"


def _get_supabase_conn():
    """Connect to Supabase PostgreSQL."""
    return psycopg2.connect(SUPABASE_URL)


def _migrate_rag_data(conn):
    """Insert rag_data rows in batches."""
    cur = conn.cursor()
    logger.info("Reading rag_data CSV...")

    with open(RAG_DATA_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        batch = []
        total = 0

        for row in reader:
            batch.append((
                int(row["id"]),
                row["chunk_text"],
                row["search_vector"] or None,
                row["source"] or None,
                row["doc_type"] or None,
                row["module"] or None,
                row["api_name"] or None,
                row["ingested_at"] or None,
            ))

            if len(batch) >= BATCH_SIZE:
                cur.executemany("""
                    INSERT INTO rag.rag_data 
                    (id, chunk_text, search_vector, source, doc_type, module, api_name, ingested_at)
                    VALUES (%s, %s, %s::tsvector, %s, %s, %s, %s, %s)
                    ON CONFLICT (id) DO NOTHING
                """, batch)
                conn.commit()
                total += len(batch)
                logger.info(f"Inserted {total:,} rows...")
                batch = []
                time.sleep(0.05)

        # Insert remaining
        if batch:
            cur.executemany("""
                INSERT INTO rag.rag_data 
                (id, chunk_text, search_vector, source, doc_type, module, api_name, ingested_at)
                VALUES (%s, %s, %s::tsvector, %s, %s, %s, %s, %s)
                ON CONFLICT (id) DO NOTHING
            """, batch)
            conn.commit()
            total += len(batch)

    logger.success(f"✅ rag_data migration complete! {total:,} rows inserted.")
    cur.close()


def _migrate_users(conn):
    """Insert users rows."""
    cur = conn.cursor()
    logger.info("Reading users CSV...")

    with open(USERS_CSV, encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    for row in rows:
        cur.execute("""
            INSERT INTO rag.users (id, username, email, password_hash, role, created_at)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO NOTHING
        """, (
            int(row["id"]),
            row["name"],
            row["email"],
            row["password"],
            row["role"],
            row["created_at"] or None,
        ))

    conn.commit()
    logger.success(f"✅ Users migration complete! {len(rows)} users inserted.")
    cur.close()

# ── 🚀 Public Endpoints ────────────────────────────────────────────────────

def migrate():
    logger.info("Connecting to Supabase...")
    conn = _get_supabase_conn()

    #_migrate_rag_data(conn)
    _migrate_users(conn)

    conn.close()
    logger.success("🎉 All data migrated to Supabase successfully!")


if __name__ == "__main__":
    migrate()