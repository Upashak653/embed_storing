"""Query ArcadeDB knowledge graph to enhance retrieval."""

# ── Imports ────────────────────────────────────────────────────────────────
import re

import psycopg2

from config import SUPABASE_DB_URL
from database import arcade_cmd


# ── 🛠️ Internal Helpers ───────────────────────────────────────────────────

def _supabase_conn():
    return psycopg2.connect(SUPABASE_DB_URL)


def _get_related_chunk_ids(chunk_id: int) -> list[dict]:
    neighbors = []
    for edge_type in ["SHARES_PARAM", "SHARES_ENTITY"]:
        out = arcade_cmd(f"SELECT expand(out('{edge_type}')) FROM Chunk WHERE chunk_id = {chunk_id} LIMIT 5")
        inn = arcade_cmd(f"SELECT expand(in('{edge_type}')) FROM Chunk WHERE chunk_id = {chunk_id} LIMIT 5")
        for v in out.get("result", []) + inn.get("result", []):
            nid = v.get("chunk_id")
            if nid is not None:
                neighbors.append({"id": nid, "strength": 0.5})
    return neighbors


def _get_chunk_by_id(chunk_id: int) -> str | None:
    """Fetch chunk_text from Supabase by id."""
    try:
        with _supabase_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT chunk_text FROM rag.rag_data WHERE id = %s", (chunk_id,))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        print(f"[ARCADE] _get_chunk_by_id error: {e}")
        return None


def _get_best_connected_chunk(api_name: str) -> int | None:
    """Find a RESTParameter chunk for this API that has SHARES_PARAM edges — from Supabase."""
    try:
        with _supabase_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id FROM rag.rag_data
                    WHERE chunk_text LIKE %s
                      AND chunk_text LIKE '%%Param_Name:%%'
                      AND chunk_text NOT LIKE '%%Param_Name: $%%'
                      AND chunk_text NOT LIKE '%%Param_Name: (no params)%%'
                      AND chunk_text NOT LIKE '%%Param_Name: to\\_%%'
                      AND chunk_text NOT LIKE '%%Param_Name: error%%'
                    ORDER BY id
                    LIMIT 1
                """, (f'%API_TechnicalName: {api_name} %',))
                row = cur.fetchone()
                return row[0] if row else None
    except Exception as e:
        print(f"[ARCADE] _get_best_connected_chunk error: {e}")
        return None


def _to_7(row: tuple, route: str) -> tuple:
    if len(row) >= 7:
        return row[:7]
    return (*row[:6], route)


# ── 🚀 Public Endpoints ────────────────────────────────────────────────────

def expand_with_graph(initial_results: list, top_k: int = 5) -> list:
    """
    Takes dedup results (6-element tuples) and expands via ArcadeDB graph edges.
    Returns merged, deduplicated, API-unique results as 7-element tuples.
    Chunk text is fetched from Supabase.
    """
    seen_ids: dict[int, tuple] = {
        row[0]: _to_7(row, "hybrid") for row in initial_results
    }

    api_pattern_expand = re.compile(r"API_TechnicalName:\s*([^|]+)")

    for row in initial_results:
        chunk_id     = row[0]
        parent_score = row[5]

        m = api_pattern_expand.search(row[1])
        api_name = m.group(1).strip() if m else None
        traversal_id = _get_best_connected_chunk(api_name) if api_name else chunk_id
        if not traversal_id:
            traversal_id = chunk_id

        neighbors = _get_related_chunk_ids(traversal_id)
        print(f"[ARCADE] chunk_id={chunk_id} traversal={traversal_id} → {len(neighbors)} neighbours")

        for neighbor in neighbors:
            nid = neighbor["id"]
            if nid in seen_ids:
                continue

            chunk = _get_chunk_by_id(nid)
            if not chunk:
                continue

            score = round(float(neighbor["strength"]) * float(parent_score), 5)
            seen_ids[nid] = (nid, chunk, None, None, score, score, "graph_expansion")

    merged = sorted(seen_ids.values(), key=lambda x: x[5], reverse=True)

    api_pattern = re.compile(r"API_TechnicalName:\s*([^|]+)")
    seen_apis: set[str] = set()
    deduped: list[tuple] = []

    for row in merged:
        m = api_pattern.search(row[1])
        api = m.group(1).strip().lower() if m else f"UNKNOWN_{row[0]}"
        if api in seen_apis:
            continue
        seen_apis.add(api)
        deduped.append(row)
        if len(deduped) == top_k:
            break

    return deduped


def apply_feedback(chunk_id: int, vote: str) -> bool:
    delta = 0.05 if vote == "up" else -0.05
    updated = 0
    for edge_type in ["SHARES_PARAM", "SHARES_ENTITY", "RELATES_TO"]:
        out_result = arcade_cmd(f"SELECT expand(outE('{edge_type}')) FROM Chunk WHERE chunk_id = {chunk_id}")
        in_result  = arcade_cmd(f"SELECT expand(inE('{edge_type}')) FROM Chunk WHERE chunk_id = {chunk_id}")
        all_edges  = out_result.get("result", []) + in_result.get("result", [])

        for edge in all_edges:
            rid      = edge.get("@rid")
            strength = float(edge.get("strength", 0.5))
            if not rid:
                continue
            new_strength   = round(min(max(strength + delta, 0.0), 1.0), 4)
            updated_result = arcade_cmd(f"UPDATE {rid} SET strength = {new_strength}")
            if "error" not in updated_result:
                updated += 1
            else:
                print(f"[FEEDBACK] Failed to update edge {rid}: {updated_result.get('detail')}")

    return updated