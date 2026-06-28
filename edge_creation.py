import psycopg2
import requests
from config import DB_CONFIG

ARCADE_BASE = "http://localhost:2480"
ARCADE_AUTH = ("root", "Upashak1234567")
ARCADE_DB   = "sap_knowledge"


def arcade_cmd(command: str) -> dict:
    """Execute single ArcadeDB SQL command."""
    command = command.strip()
    if not command: return {}
    res = requests.post(
        f"{ARCADE_BASE}/api/v1/command/{ARCADE_DB}",
        auth=ARCADE_AUTH,
        headers={
            "Content-Type": "application/json",
            "Accept":       "application/json",
        },
        json={"language": "sql", "command": command},
        timeout=30,
    )
    if res.status_code != 200:  print(f"[ARCADE ERROR] Status {res.status_code}: {res.text}")
    return res.json()


def execute_arcade_batch(statements: list[str]) -> None:
    """Execute a list of statements one by one."""
    for statement in statements:    arcade_cmd(statement)


def rebuild_semantic_edges(
    distance_threshold: float = 0.95,
    top_k: int = 3,
    batch_size: int = 100
) -> None:
    # Clear old edges
    arcade_cmd("DELETE FROM RELATES_TO")
    print("[REBUILD] Cleared historical graph edges.")

    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor(name="chunk_cursor") as server_cursor:
            server_cursor.execute("SELECT id, source FROM rag.rag_data ORDER BY id;")

            edge_buffer = []
            total_edges = 0
            processed_chunks = 0

            with conn.cursor() as lookup_cur:
                for chunk_id, source in server_cursor:
                    processed_chunks += 1

                    lookup_cur.execute("""
                        SELECT id,
                            (embedding <-> (SELECT embedding FROM rag.rag_data WHERE id = %s)) AS distance
                        FROM rag.rag_data
                        WHERE id != %s
                        AND source = %s
                        AND embedding <-> (SELECT embedding FROM rag.rag_data WHERE id = %s) <= %s
                        ORDER BY embedding <-> (SELECT embedding FROM rag.rag_data WHERE id = %s)
                        LIMIT %s;
                    """, (chunk_id, chunk_id, source, chunk_id, distance_threshold, chunk_id, top_k))

                    neighbors = lookup_cur.fetchall()

                    for neighbor_id, distance in neighbors:
                        strength = round(1.0 / (1.0 + float(distance)), 4)
                        statement = (
                            f"CREATE EDGE RELATES_TO "
                            f"FROM (SELECT FROM Chunk WHERE chunk_id = {chunk_id}) "
                            f"TO (SELECT FROM Chunk WHERE chunk_id = {neighbor_id}) "
                            f"SET strength = {strength}"
                        )
                        edge_buffer.append(statement)
                        total_edges += 1

                    if len(edge_buffer) >= batch_size:
                        execute_arcade_batch(edge_buffer)
                        edge_buffer = []
                        print(f"[REBUILD] Processed {processed_chunks} nodes... Generated {total_edges} graph edges.")

                if edge_buffer:
                    execute_arcade_batch(edge_buffer)

    print(f"\n[SUCCESS] Rebuild pipeline complete. {total_edges} semantic edges written to Graph.")

# ── NEW: Structured edge types ────────────────────────────────────────────────
# Added below — original rebuild_semantic_edges is completely untouched above.
# RELATES_TO edges are never deleted by these new functions.

def build_param_edges(min_apis: int = 2, max_apis: int = 15, batch_size: int = 100,)-> None:
    """
    Creates SHARES_PARAM edges between chunks whose APIs share
    the same meaningful Param_Name (excluding OData noise params).
 
    Strength = 1.0 / api_count — rarer shared params = stronger connection.
    e.g. param shared by 2 APIs  → strength 0.50
         param shared by 15 APIs → strength 0.07
    """
    print("\n[SHARES_PARAM] Building cross-API parameter edges...")

    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH parsed AS (
                    SELECT
                        id,
                        split_part(split_part(chunk_text, 'API_TechnicalName: ', 2), ' |', 1) AS api_name,
                        split_part(split_part(chunk_text, 'Param_Name: ', 2),       ' |', 1) AS param
                    FROM rag.rag_data
                    WHERE chunk_text LIKE '%%Param_Name:%%'
                ),
                filtered AS (
    SELECT id, api_name, param
    FROM parsed
    WHERE param != ''
      AND LENGTH(param) > 4
      AND param NOT LIKE '$%%'
      AND param != 'error'
      AND param != '(no params)'
      AND param NOT LIKE 'to_%%'
      AND param NOT IN (
          'Plant', 'Batch', 'Region', 'Language', 'Currency',
          'CompanyCode', 'Country', 'CreationDate', 'CreatedByUser',
          'LastChangeDate', 'Material', 'StorageLocation', 'POBox',
          'CityName', 'PostalCode', 'StreetName', 'POBoxPostalCode'
      )
),
                api_counts AS (
                    SELECT param, COUNT(DISTINCT api_name) AS api_count
                    FROM filtered
                    GROUP BY param
                    HAVING COUNT(DISTINCT api_name) BETWEEN %s AND %s
                ),
                        representatives AS (
                    SELECT DISTINCT ON (f.param, f.api_name)
                        f.param, f.api_name, f.id AS chunk_id
                    FROM filtered f
                    JOIN api_counts ac ON f.param = ac.param
                    ORDER BY f.param, f.api_name, f.id
                )
                SELECT
                    a.chunk_id  AS chunk_id_1,
                    b.chunk_id  AS chunk_id_2,
                    a.param,
                    ac.api_count,
                    ROUND(1.0 / ac.api_count, 4) AS strength
                FROM representatives a
                JOIN representatives b
                    ON a.param = b.param AND a.api_name < b.api_name
                JOIN api_counts ac ON a.param = ac.param
                ORDER BY strength DESC;
            """, (min_apis, max_apis))

            rows = cur.fetchall()

    print(f"[SHARES_PARAM] {len(rows)} cross-API param edges found...")

    edge_buffer = []
    total = 0
 
    for chunk_id_1, chunk_id_2, param, api_count, strength in rows:
        safe_param = param.replace("'", "")
        statement = (
            f"CREATE EDGE SHARES_PARAM "
            f"FROM (SELECT FROM Chunk WHERE chunk_id = {chunk_id_1}) "
            f"TO   (SELECT FROM Chunk WHERE chunk_id = {chunk_id_2}) "
            f"SET param = '{safe_param}', strength = {strength}"
        )
        edge_buffer.append(statement)
        total += 1
 
        if len(edge_buffer) >= batch_size:
            execute_arcade_batch(edge_buffer)
            edge_buffer = []
            print(f"[SHARES_PARAM] {total}/{len(rows)} edges created...")
 
    if edge_buffer:
        execute_arcade_batch(edge_buffer)
 
    print(f"[SHARES_PARAM] Done — {total} SHARES_PARAM edges created.")
def build_entity_edges( min_apis: int = 2, max_apis: int = 10, batch_size: int = 100,) -> None:

    """
    Creates SHARES_ENTITY edges between chunks whose APIs share
    the same meaningful EntitySet path.
 
    Strength fixed at 0.9 — entity sharing is a very strong signal.
    """

    print("\n[SHARES_ENTITY] Building cross-API entity edges...")

    with psycopg2.connect(**DB_CONFIG) as conn:
        with conn.cursor() as cur:
            cur.execute("""
                WITH parsed AS (
                    SELECT
                        id,
                        split_part(split_part(chunk_text, 'API_TechnicalName: ', 2), ' |', 1) AS api_name,
                        split_part(split_part(chunk_text, 'EntitySet: ', 2),         ' |', 1) AS entity
                    FROM rag.rag_data
                    WHERE chunk_text LIKE '%%EntitySet: /%%'
                ),
                filtered AS (
                    SELECT id, api_name, entity
                    FROM parsed
                    WHERE entity != ''
                      AND entity NOT LIKE '/$$%%'
                      AND entity NOT IN (
                          '/Cancel', '/Release', '/Reject', '/Accept',
                          '/Confirm', '/Complete', '/Reopen', '/Close',
                          '/SubmitForApproval', '/WithdrawFromApproval',
                          '/SetIsEndOfPurpose'
                      )
                ),
                api_counts AS (
                    SELECT entity, COUNT(DISTINCT api_name) AS api_count
                    FROM filtered
                    GROUP BY entity
                    HAVING COUNT(DISTINCT api_name) BETWEEN %s AND %s
                ),
                representatives AS (
                    SELECT DISTINCT ON (f.entity, f.api_name)
                        f.entity, f.api_name, f.id AS chunk_id
                    FROM filtered f
                    JOIN api_counts ac ON f.entity = ac.entity
                    ORDER BY f.entity, f.api_name, f.id
                )
                SELECT
                    a.chunk_id AS chunk_id_1,
                    b.chunk_id AS chunk_id_2,
                    a.entity,
                    0.9        AS strength
                FROM representatives a
                JOIN representatives b
                    ON a.entity = b.entity AND a.api_name < b.api_name
                JOIN api_counts ac ON a.entity = ac.entity
                ORDER BY a.entity;
            """, (min_apis, max_apis))

            rows = cur.fetchall()
            print(f"[SHARES_ENTITY] {len(rows)} cross-API entity edges found...")
 
    edge_buffer = []
    total = 0
 
    for chunk_id_1, chunk_id_2, entity, strength in rows:
        safe_entity = entity.replace("'", "")
        statement = (
            f"CREATE EDGE SHARES_ENTITY "
            f"FROM (SELECT FROM Chunk WHERE chunk_id = {chunk_id_1}) "
            f"TO   (SELECT FROM Chunk WHERE chunk_id = {chunk_id_2}) "
            f"SET entity = '{safe_entity}', strength = {strength}"
        )
        edge_buffer.append(statement)
        total += 1
 
        if len(edge_buffer) >= batch_size:
            execute_arcade_batch(edge_buffer)
            edge_buffer = []
            print(f"[SHARES_ENTITY] {total}/{len(rows)} edges created...")
 
    if edge_buffer:
        execute_arcade_batch(edge_buffer)
 
    print(f"[SHARES_ENTITY] Done — {total} SHARES_ENTITY edges created.")
 
 
def build_all_semantic_edges() -> None:
    """
    Builds SHARES_PARAM and SHARES_ENTITY edges.
    RELATES_TO edges are never touched — all existing edges preserved.
    """
    print("[SEMANTIC EDGES] Building new structured edge types...")
    print("[SEMANTIC EDGES] RELATES_TO edges untouched — all existing edges preserved.\n")

    # Create edge types if they don't exist yet
    arcade_cmd("CREATE EDGE TYPE SHARES_PARAM IF NOT EXISTS")
    arcade_cmd("CREATE EDGE TYPE SHARES_ENTITY IF NOT EXISTS")

    build_param_edges(min_apis=2, max_apis=15, batch_size=100)
    build_entity_edges(min_apis=2, max_apis=10, batch_size=100)

    print("\n[SEMANTIC EDGES] Complete!")
 
 
if __name__ == "__main__":
    arcade_cmd("DELETE FROM SHARES_PARAM")
    print("Cleared old SHARES_PARAM edges")
    build_all_semantic_edges()


#if __name__ == "__main__":
 #   rebuild_semantic_edges(distance_threshold=0.95, top_k=3, batch_size=100)