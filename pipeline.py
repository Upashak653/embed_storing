# pipeline.py
import psycopg2
from pathlib import Path
from config import DB_CONFIG, client, EMBEDDING_MODEL
from readers import file_read_route

# Import arcade_cmd to seamlessly synchronize graph vertices
from database import arcade_cmd

def run_ingestion_pipeline(file_path: str, batch_size: int = 100, limit: int = None):

    if not Path(file_path).exists():
        print(f"[PIPELINE] File not found: {file_path}")
        return

    source_name = Path(file_path).stem
    chunks = file_read_route(file_path)

    if not chunks:
        print("[PIPELINE] Zero processing segments extracted. Halting.")
        return

    if limit is not None:   
        chunks = chunks[:limit]

    total_chunks = len(chunks)
    print(f"\n[PIPELINE] Running engine over {total_chunks} chunk targets...")

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                inserted = skipped = failed = 0
                
                # Step 1: Scan for existing chunks to prevent double-processing
                print("[PIPELINE] Scanning workspace indexes for existing records...")
                cur.execute("SELECT chunk_text FROM rag.rag_data WHERE source = %s;", (source_name,))
                existing_set = {row[0] for row in cur.fetchall()}

                # Slice chunks into high-density processing windows
                for i in range(0, total_chunks, batch_size):
                    batch_window = chunks[i : i + batch_size]
                    
                    # Filter out nodes that already exist in database index
                    valid_batch = [c for c in batch_window if c not in existing_set]
                    skipped += len(batch_window) - len(valid_batch)
                    
                    if not valid_batch:
                        continue

                    try:
                        # Step 2: High-speed Parallel API Embedding Request
                        response = client.embeddings.create(
                            input=valid_batch,
                            model=EMBEDDING_MODEL
                        )
                        embeddings = [item.embedding for item in response.data]

                        # Step 3: Fast Multi-Row SQL Insert with Key Recovery
                        insert_args = []
                        for text, vec in zip(valid_batch, embeddings):  
                            insert_args.extend([text, str(vec), text, source_name])

                        value_templates = ", ".join(["(%s, %s, to_tsvector('english', %s), %s, now())"] * len(valid_batch))
                        
                        # FIXED: Added RETURNING id to instantly extract serial tracking keys
                        query = f"""
                            INSERT INTO rag.rag_data 
                            (chunk_text, embedding, search_vector, source, ingested_at)
                            VALUES {value_templates}
                            ON CONFLICT (chunk_text) DO NOTHING
                            RETURNING id;
                        """
                        
                        cur.execute(query, insert_args)
                        returned_ids = [row[0] for row in cur.fetchall()]
                        
                        # Step 4: Mirror the exact keys directly into ArcadeDB graph vertices
                        # This creates all anchor items for the edge builder
                        for new_id in returned_ids:
                            arcade_cmd(f"CREATE VERTEX Chunk SET chunk_id = {new_id}")

                        inserted += len(returned_ids)
                        
                        # Print performance milestones
                        current_progress = min(i + batch_size, total_chunks)
                        print(f"[{current_progress}/{total_chunks}] Progress: Added {len(returned_ids)} records to Hybrid Storage Layers | Total Skipped: {skipped}")

                    except Exception as batch_err:
                        print(f"\n[BATCH FAULT] Skipping block index window {i}-{i+batch_size}: {batch_err}")
                        failed += len(valid_batch)
                        conn.rollback()
                        continue

                conn.commit()
        print(f"\n[SUCCESS] Pipeline Complete! New synchronized records: {inserted} | Unaltered items: {skipped}")
    
    except Exception as e:
        print(f"\n[FATAL SYSTEM EXCEPTION] Ingestion sequence broke down: {e}")