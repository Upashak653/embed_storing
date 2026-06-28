"""Exposes the retrieval endpoints with unified 6-element RRF layouts."""

import psycopg2
import re
from config import SUPABASE_DB_URL, pinecone_index

from database import get_embedding

# ── 🛠️ Constants ─────────────────────────────────────────────────────────────
_MIN_SCORE         = 0.00001
_SHORT_QUERY_FLOOR = 0.04      # was 0.15 — too aggressive (RRF max per source ≈ 0.047)
_VECTOR_LIMIT      = 1000      # was 100 — too low for 76K-row corpus
 
 # ── 🛠️ Internal Helpers ──────────────────────────────────────────────────────

def _supabase_connection():
    """Get a connection to Supabase PostgreSQL."""
    return psycopg2.connect(SUPABASE_DB_URL)


def _clean_query(query: str) -> str:
    noise = { "vs", "versus", "and", "or", "the", "a", "an", "how", "what", "is", "are", "in", "for", "with" }
    query = query.replace("_", " ")
    return " ".join(w for w in query.lower().split() if w not in noise)

def _safe_boost_pattern(cq: str)->str:
    """
    Build a field-safe regex pattern for title/name boosting.
    Uses [^|]* instead of .* to stop at field delimiters.
    """
    return cq.replace(" ","[^|]*")

def _normalize_scores(rows: list[tuple]) -> list[tuple]:
    if not rows: return rows

    max_score = rows[0][5]
    if max_score == 0:  return rows

    return [(*row[:5], round(row[5] / max_score, 5)) for row in rows]

def _pinecone_vector_Search(query_embedding: list[float], top_k: int = 1000) -> dict[int , int]:
    """
    Query Pinecone for top_k similar vectors.
    Returns {chunk_id: rank} dict.
    """
    results = pinecone_index.query(
        vector=query_embedding,
        top_k=top_k,
        include_values=False,
    )
    return {int(match["id"]): rank + 1 for rank, match in enumerate(results["matches"])}

def _fetch_chunks_by_ids(ids: list[int])-> dict[int, str]:
    """Fetch chunk_text from Supabase by list of IDs."""
    if not ids:
        return {}
    with _supabase_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT id, chunk_text FROM rag.rag_data WHERE id = ANY(%s)",
                (ids,)
            )
            return {row[0]: row[1] for row in cur.fetchall()}
 
def _bm25_search(cq: str, limit: int = 1000) -> dict[int, int]:
    """
    BM25 keyword search on Supabase tsvector.
    Returns {chunk_id: rank} dict.
    """
    try:
        with _supabase_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id,
                           ROW_NUMBER() OVER (
                               ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('simple', %s)) DESC
                           ) AS rank
                    FROM rag.rag_data
                    WHERE search_vector @@ websearch_to_tsquery('simple', %s)
                    ORDER BY ts_rank_cd(search_vector, websearch_to_tsquery('simple', %s)) DESC
                    LIMIT %s
                """, (cq, cq, cq, limit))
                return {row[0]: row[1] for row in cur.fetchall()}
    except Exception as e:
        print(f"[BM25] Error: {e}")
        return {}
    
def _ilike_search(cq: str, strict: bool = False) -> dict[int, int]:
    """
    ILIKE / regex search on Supabase chunk_text.
    strict=True uses word boundary regex (for short queries).
    Returns {chunk_id: rank} dict.
    """
    try:
        with _supabase_connection() as conn:
            with conn.cursor() as cur:
                if strict:
                    cur.execute("""
                        SELECT DISTINCT ON (api_name) id, rank
                        FROM (
                            SELECT
                                id,
                                split_part(split_part(chunk_text, 'API_TechnicalName: ', 2), ' |', 1) AS api_name,
                                ROW_NUMBER() OVER (ORDER BY id) + 20 AS rank
                            FROM rag.rag_data
                            WHERE chunk_text ~* (%(pattern)s)
                        ) sub
                        ORDER BY api_name, rank
                    """, {"pattern": f"\\m{cq}\\M"})
                else:
                    cur.execute("""
                        SELECT DISTINCT ON (api_name) id, rank
                        FROM (
                            SELECT
                                id,
                                split_part(split_part(chunk_text, 'API_TechnicalName: ', 2), ' |', 1) AS api_name,
                                ROW_NUMBER() OVER (ORDER BY id) + 20 AS rank
                            FROM rag.rag_data
                            WHERE chunk_text ILIKE %(pattern)s
                        ) sub
                        ORDER BY api_name, rank
                    """, {"pattern": f"%{cq}%"})
                return {row[0]: row[1] for row in cur.fetchall()}
    except Exception as e:
        print(f"[ILIKE] Error: {e}")
        return {}
 
def _rrf_fusion(
    vector_ranks: dict[int, int],
    keyword_ranks: dict[int, int],
    chunk_texts: dict[int, str],
    cq: str,
    top_k: int,
) -> list[tuple]:
    """
    RRF fusion of Pinecone vector ranks + Supabase BM25/ILIKE ranks.
    Applies title/name boost. Returns list of 6-element tuples.
    """
    safe_pattern = _safe_boost_pattern(cq)
    all_ids = set(vector_ranks) | set(keyword_ranks)
 
    rows = []
    for chunk_id in all_ids:
        chunk_text = chunk_texts.get(chunk_id)
        if not chunk_text:
            continue
 
        v_rank = vector_ranks.get(chunk_id)
        k_rank = keyword_ranks.get(chunk_id)
 
        base_rrf = (
            (1.0 / (20.0 + v_rank) if v_rank else 0.0) +
            (1.0 / (20.0 + k_rank) if k_rank else 0.0)
        )
 
        # Title/name boost
        ct_lower = chunk_text.lower()
        if re.search(r"api_title:[^|]*" + safe_pattern + r"\s*\(", ct_lower):
            boosted = base_rrf * 8.0
        elif re.search(r"api_technicalname:[^|]*" + safe_pattern, ct_lower):
            boosted = base_rrf * 4.0
        elif re.search(r"api_title:[^|]*" + safe_pattern, ct_lower):
            boosted = base_rrf * 4.0
        else:
            boosted = base_rrf
 
        rows.append((chunk_id, chunk_text, v_rank, k_rank, base_rrf, boosted))
 
    rows.sort(key=lambda x: x[5], reverse=True)
    return rows[:top_k]
 
        
def _run_hybrid(query_embedding: list[float], cq: str, top_k: int, strict: bool = False) -> list[tuple]:
    """Full hybrid search: Pinecone vectors + Supabase BM25 + ILIKE → RRF."""
    # 1. Vector search via Pinecone
    vector_ranks = _pinecone_vector_Search(query_embedding, top_k=_VECTOR_LIMIT)
 
    # 2. BM25 on Supabase
    bm25_ranks = _bm25_search(cq, limit=1000)
 
    # 3. ILIKE on Supabase
    ilike_ranks = _ilike_search(cq, strict=strict)
 
    # 4. Merge keyword ranks (BM25 + ILIKE)
    keyword_ranks: dict[int, int] = {}
    for chunk_id, rank in {**bm25_ranks, **ilike_ranks}.items():
        if chunk_id not in keyword_ranks or rank < keyword_ranks[chunk_id]:
            keyword_ranks[chunk_id] = rank
 
    # 5. Fetch chunk texts for all candidate IDs
    all_ids = list(set(vector_ranks) | set(keyword_ranks))
    chunk_texts = _fetch_chunks_by_ids(all_ids)
 
    # 6. RRF fusion + boost
    return _rrf_fusion(vector_ranks, keyword_ranks, chunk_texts, cq, top_k)
 
def _print_hybrid_results(results: list[tuple], label: str) -> None:
    print(f"\n{'='*55}")
    print(f"  {label}")
    print(f"{'='*55}")
    for i, (id, chunk_text, v_rank, k_rank, base_score, boosted_score) in enumerate(results):
        v_str = f"#{v_rank}" if v_rank else "Not in Top"
        k_str = f"#{k_rank}" if k_rank else "Not in Top"
        print(f"\n--- Result {i+1} [ID: {id}] ---")
        print(f"  Vector Rank   : {v_str}")
        print(f"  Keyword Rank  : {k_str}")
        print(f"  Raw RRF Score : {base_score:.5f}")
        print(f"  Boosted Score : {boosted_score:.5f}")
        print(f"\n{chunk_text}")
        print("-" * 55)



# ── 🚀 Public Endpoints ────────────────────────────────────────────────────
 
def hybrid_search(query: str, top_k: int = 5) -> list:
    query_embedding = get_embedding(query)
    if query_embedding is None:
        print("[HYBRID SEARCH] Embedding failed.")
        return []
    cq = _clean_query(query)
    results = _run_hybrid(query_embedding, cq, top_k)
    _print_hybrid_results(results, f"HYBRID SEARCH: '{query}'")
    return results

def deduplicated_hybrid_search(
    query: str,
    top_k: int = 5,
    silent: bool = False,
    min_score: float = 0.0,
) -> list:
    embedding = get_embedding(query)
    if embedding is None:
        print("[DEDUP SEARCH] Embedding failed.")
        return []
 
    cq = _clean_query(query)
    is_short = len(cq.split()) == 1
 
    raw_rows = _run_hybrid(embedding, cq, top_k=5000, strict=is_short)
 
    api_pattern = re.compile(r"API_TechnicalName:\s*([^|]+)")
    seen_apis: set[str] = set()
    deduped: list[tuple] = []
 
    for row in raw_rows:
        chunk_text    = row[1]
        k_rank        = row[3]
        boosted_score = row[5]
 
        if boosted_score < _MIN_SCORE:
            continue
 
        if "Object_Type: RESTParameter" in chunk_text:
            param_match = re.search(r"Param_Name:\s*([^|]+)", chunk_text)
            if param_match:
                pname = param_match.group(1).strip()
                if pname.startswith("$") or pname.startswith("to_") or pname in ("error", "(no params)"):
                    continue
 
        if is_short and (k_rank is None) and (boosted_score < _SHORT_QUERY_FLOOR):
            continue
 
        match = api_pattern.search(chunk_text)
        api = match.group(1).strip().lower() if match else f"UNKNOWN_{hash(chunk_text)}"
 
        if api in seen_apis:
            continue
 
        seen_apis.add(api)
        deduped.append(row)
 
        if len(deduped) == top_k:
            break
 
    deduped = _normalize_scores(deduped)
 
    if min_score > 0.0:
        deduped = [row for row in deduped if row[5] >= min_score]
 
    return deduped
 
 
def search_by_source(query: str, source: str = None, top_k: int = 5) -> list:
    embedding = get_embedding(query)
    if embedding is None:
        return []
 
    cq = _clean_query(query)
    vector_ranks = _pinecone_vector_Search(embedding, top_k=50)
    bm25_ranks   = _bm25_search(cq, limit=50)
 
    keyword_ranks: dict[int, int] = {**bm25_ranks}
    all_ids = list(set(vector_ranks) | set(keyword_ranks))
 
    # Filter by source in Supabase
    try:
        with _supabase_connection() as conn:
            with conn.cursor() as cur:
                if source:
                    cur.execute(
                        "SELECT id, chunk_text FROM rag.rag_data WHERE id = ANY(%s) AND source = %s",
                        (all_ids, source)
                    )
                else:
                    cur.execute(
                        "SELECT id, chunk_text FROM rag.rag_data WHERE id = ANY(%s)",
                        (all_ids,)
                    )
                chunk_texts = {row[0]: row[1] for row in cur.fetchall()}
    except Exception as e:
        print(f"[SOURCE SEARCH] Error: {e}")
        return []
 
    results = _rrf_fusion(vector_ranks, keyword_ranks, chunk_texts, cq, top_k)
    _print_hybrid_results(results, f"SOURCE SEARCH [{source or 'ALL'}]: '{query}'")
    return results
    