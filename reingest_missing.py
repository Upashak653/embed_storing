# reingest_missing.py
import psycopg2
import re
import pandas as pd
from pathlib import Path
from config import DB_CONFIG, client, EMBEDDING_MODEL
from database import arcade_cmd
from readers import file_read_route

EXCEL_FILE = 'sap_api_details_20260521_1435 1.xlsx'

# Step 1: Find missing APIs
print("[STEP 1] Finding missing APIs...")
df = pd.read_excel(EXCEL_FILE, sheet_name='All_Parameters')
excel_apis = set(df['API_TechnicalName'].dropna().unique())

conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
cur.execute("SELECT DISTINCT chunk_text FROM rag.rag_data")
pattern = re.compile(r"API_TechnicalName:\s*([^\s|]+)")
db_apis = set()
for row in cur.fetchall():
    m = pattern.search(row[0])
    if m:
        db_apis.add(m.group(1).strip())
conn.close()

missing_apis = excel_apis - db_apis
# Filter out junk entries
missing_apis = {a for a in missing_apis if a.startswith('OP_API_') or a.startswith('OP_A_') or a.startswith('OP_C_') or a.startswith('OP_LMD') or a.startswith('OP_ODATA')}
print(f"Excel: {len(excel_apis)} | DB: {len(db_apis)} | Missing: {len(missing_apis)}")

# Step 2: Get all chunks from Excel for missing APIs only
print("[STEP 2] Reading all chunks from Excel...")
all_chunks = file_read_route(EXCEL_FILE)
print(f"Total chunks from Excel: {len(all_chunks)}")

# Step 3: Filter only chunks belonging to missing APIs
api_pattern = re.compile(r"API_TechnicalName:\s*([^\s|]+)")
missing_chunks = []
for chunk in all_chunks:
    m = api_pattern.search(chunk)
    if m:
        api = m.group(1).strip()
        if api in missing_apis:
            missing_chunks.append(chunk)

print(f"Chunks to ingest: {len(missing_chunks)}")

# Step 4: Ingest in batches
BATCH_SIZE = 100
source_name = Path(EXCEL_FILE).stem
inserted = skipped = failed = 0

# Get existing chunks to avoid duplicates
conn = psycopg2.connect(**DB_CONFIG)
cur = conn.cursor()
cur.execute("SELECT chunk_text FROM rag.rag_data WHERE source = %s", (source_name,))
existing_set = {row[0] for row in cur.fetchall()}
conn.close()

valid_chunks = [c for c in missing_chunks if c not in existing_set]
skipped = len(missing_chunks) - len(valid_chunks)
print(f"After dedup: {len(valid_chunks)} chunks to insert | {skipped} already exist")

try:
    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            for i in range(0, len(valid_chunks), BATCH_SIZE):
                batch = valid_chunks[i:i+BATCH_SIZE]
                try:
                    response = client.embeddings.create(
                        input=batch,
                        model=EMBEDDING_MODEL
                    )
                    embeddings = [item.embedding for item in response.data]

                    insert_args = []
                    for text, vec in zip(batch, embeddings):
                        insert_args.extend([text, str(vec), text, source_name])

                    value_templates = ", ".join(
                        ["(%s, %s, to_tsvector('english', %s), %s, now())"] * len(batch)
                    )
                    query = f"""
                        INSERT INTO rag.rag_data
                        (chunk_text, embedding, search_vector, source, ingested_at)
                        VALUES {value_templates}
                        ON CONFLICT (chunk_text) DO NOTHING
                        RETURNING id;
                    """
                    cur.execute(query, insert_args)
                    returned_ids = [row[0] for row in cur.fetchall()]

                    for new_id in returned_ids:
                        arcade_cmd(f"CREATE VERTEX Chunk SET chunk_id = {new_id}")

                    inserted += len(returned_ids)
                    current = min(i + BATCH_SIZE, len(valid_chunks))
                    print(f"[{current}/{len(valid_chunks)}] Inserted {len(returned_ids)} | Total: {inserted}")

                except Exception as e:
                    print(f"[BATCH ERROR] {i}-{i+BATCH_SIZE}: {e}")
                    failed += len(batch)
                    conn.rollback()
                    continue

            conn.commit()

    print(f"\n[DONE] Inserted: {inserted} | Skipped: {skipped} | Failed: {failed}")

except Exception as e:
    print(f"[FATAL] {e}")