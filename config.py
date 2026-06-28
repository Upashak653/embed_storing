"""Manages your environment states and configures singletons for downstream consumption."""

from dotenv import load_dotenv
from openai import OpenAI
from pinecone import Pinecone
import os


load_dotenv()
client = OpenAI()

# ── Pinecone ──────────────────────────────────────────────────────────────
PINECONE_API_KEY = os.getenv("PINECONE_API_KEY")
PINECONE_HOST    = os.getenv("PINECONE_HOST")
pinecone_index   = Pinecone(api_key=PINECONE_API_KEY).Index(host=PINECONE_HOST)

# ── Supabase (PostgreSQL) ─────────────────────────────────────────────────
SUPABASE_DB_URL = os.getenv("SUPABASE_DB_URL")  # session pooler URL
 

# ── ArcadeDB (still local) ────────────────────────────────────────────────
ARCADE_BASE = f"http://{os.getenv('ARCADE_HOST', 'localhost')}:2480"
ARCADE_AUTH = (os.getenv("ARCADE_USER", "root"), os.getenv("ARCADE_PASSWORD", "Upashak1234567"))
ARCADE_DB   = "sap_knowledge"


# ── Local DB (for ArcadeDB graph queries only) ────────────────────────────
DB_CONFIG = {
    "dbname": os.getenv("DB_NAME", "asis"),
    "user": os.getenv("DB_USER", "postgres"),
    "password": os.getenv("DB_PASSWORD"),
    "host": os.getenv("DB_HOST", "localhost"),
    "port": os.getenv("DB_PORT", "5432")
}

# Shared RAG Tuning Hyperparameters
CHUNK_SIZE = 600
CHUNK_OVERLAP = 150
EMBEDDING_MODEL = "text-embedding-3-small"

# Validate critical config on startup
if not DB_CONFIG["password"]:
    raise EnvironmentError("[CONFIG] DB_PASSWORD not set in .env file")

if not os.getenv("OPENAI_API_KEY"):
    raise EnvironmentError("[CONFIG] OPENAI_API_KEY not set in .env file")

if not PINECONE_API_KEY:
    raise EnvironmentError("[CONFIG] PINECONE_API_KEY not set in .env")

if not SUPABASE_DB_URL:
    raise EnvironmentError("[CONFIG] SUPABASE_DB_URL not set in .env")