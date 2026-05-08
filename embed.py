import psycopg2, os #psycopg2 is synchronous — when it runs a query, it blocks everything until the result comes back:
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()
client = OpenAI()

DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "asis"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5433")
}

def database_setup():
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute("CREATE SCHEMA IF NOT EXISTS rag;")
        cur.execute("""
            CREATE TABLE IF NOT EXISTS rag.rag_data (
                id bigserial PRIMARY KEY,
                chunk_text TEXT,
                embedding vector(1536)
            );
        """)
        conn.commit()
        print("Schema and table ready.")
        cur.close()
        conn.close()
    except Exception as e:
        print("Setup error:", e)

def markdown_file_read(filepath):
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()
        chunks = content.split("\n\n")
        chunks = [c.strip() for c in chunks if len(c.strip()) > 50]
        print(f"Total chunks found: {len(chunks)}")
        return chunks
    except FileNotFoundError:
        print("File not found.")
    except Exception as e:
        print("Read error:", e)

def get_embedding(text: str):
    response = client.embeddings.create(
        input=text,
        model="text-embedding-3-small"
    )
    return response.data[0].embedding

def search(query:str,top_k:int = 3):
    query_embedd=get_embedding(query)
    conn = psycopg2.connect(**DB_CONFIG)
    cur = conn.cursor()
    cur.execute("""
        SELECT id, chunk_text 
        FROM rag.rag_data 
        ORDER BY embedding <-> %s 
        LIMIT %s
    """, (str(query_embedd), top_k))
    res = cur.fetchall()
    cur.close()
    conn.close()
    
    # 3. Print results
    for i, (id, chunk_text) in enumerate(res):
        print(f"\n--- Result {i+1} (id={id}) ---")
        print(chunk_text)

def insert_to_db(chunk_text, embedding):
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO rag.rag_data (chunk_text, embedding) VALUES (%s, %s)",
            (chunk_text, str(embedding))
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print("Insert error:", e)

if __name__ == "__main__":
    database_setup()

    chunks = markdown_file_read(r"C:\Users\Upashak.gayen\Desktop\ABAP_CROSS_SERVER_MIGRATION_PROMPT.md")
    
    search("how to migrate ABAP program")