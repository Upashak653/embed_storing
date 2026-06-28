# ── Imports ─────────────────────────────────────────────────────────────────
from fastapi                    import FastAPI
from fastapi.middleware.cors    import CORSMiddleware
from fastapi.concurrency        import run_in_threadpool
from pydantic                   import BaseModel
from typing                     import Literal

from search                     import deduplicated_hybrid_search
from arcade                     import expand_with_graph, apply_feedback
from auth                       import register_user, login_user, get_user_by_token, logout_user

import psycopg2

# ── App setup ────────────────────────────────────────────────────────────────
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "https://sap-api-advisor.vercel.app",
        "https://sap-api-advisor-479lil8xx-upashak.vercel.app",
        ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic models ───────────────────────────────────────────────────────────

class SearchRequest(BaseModel):
    query:     str
    top_k:     int   = 5
    min_score: float = 0.0


class FeedbackRequest(BaseModel):
    chunk_id: int
    vote:     Literal["up", "down"]
    query:    str = ""


class SearchResult(BaseModel):
    id:          int
    api_name:    str
    api_title:   str
    api_status:  str
    param_name:  str
    param_type:  str
    param_in:    str
    required:    str
    method:      str
    entity:      str
    description: str
    score:       float
    route:       str

# ── Auth Models ───────────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    name:     str
    email:    str
    password: str
    dept:     str = ""

class LoginRequest(BaseModel):
    email:    str
    password: str

class LogoutRequest(BaseModel):
    token: str

# ── 🛠️ Helpers ────────────────────────────────────────────────────────────────
#_extract , _parse_chunk , _row_to_result
def _extract(text: str, key: str) -> str:
    try:
        return text.split(f"{key}: ")[1].split(" |")[0].strip()
    except (IndexError, AttributeError):
        return ""


def _parse_chunk(chunk_text: str) -> dict:
    return {
        "api_name":    _extract(chunk_text, "API_TechnicalName"),
        "api_title":   _extract(chunk_text, "API_Title"),
        "api_status":  _extract(chunk_text, "API_Status"),
        "param_name":  _extract(chunk_text, "Param_Name"),
        "param_type":  _extract(chunk_text, "Param_Type"),
        "param_in":    _extract(chunk_text, "Param_In"),
        "required":    _extract(chunk_text, "Param_Required"),
        "method":      _extract(chunk_text, "Path_Method"),
        "entity":      _extract(chunk_text, "EntitySet"),
        "description": _extract(chunk_text, "Description"),
    }


def _row_to_result(row: tuple) -> dict:
    route = row[6] if len(row) > 6 else "hybrid"
    return {
        "id":    row[0],
        **_parse_chunk(row[1]),
        "score": round(float(row[5]), 5),
        "route": route,
    }


# ── 🚀 Endpoints ──────────────────────────────────────────────────────────────

@app.get("/")
def root():
    return {"status": "SAP RAG API running"}


@app.get("/health")
def health():
    return {"status": "ok"}


# ── Graph expansion threshold ─────────────────────────────────────────────────
# Only expand from results scoring above this — weak results produce noisy neighbours.
# Scores are normalised 0–1 (top result = 1.0).
_GRAPH_EXPANSION_THRESHOLD = 0.15


@app.post("/search")
async def search(req: SearchRequest):

    def process_search() -> list[dict]:
        try:
            # Step 1 — dedup hybrid retrieval
            dedup_raw = deduplicated_hybrid_search(
                req.query, top_k=req.top_k, silent=True, min_score=req.min_score
            )

            # Step 2 — only expand from strong results
            # Weak matches (score < 0.15) produce noisy graph neighbours
            strong = [r for r in dedup_raw if r[5] >= _GRAPH_EXPANSION_THRESHOLD]
            seeds  = strong if strong else dedup_raw  # fallback: use all if none qualify

            # Step 3 — graph expansion via ArcadeDB
            raw = expand_with_graph(seeds, top_k=req.top_k)

            return [_row_to_result(row) for row in raw]

        except Exception as e:
            print(f"[SEARCH ERROR] query={req.query!r}: {e}")
            return []

    final_results = await run_in_threadpool(process_search)

    return {
        "query":   req.query,
        "count":   len(final_results),
        "results": final_results,
    }

# ── Feedback endpoint ────────────────────────────────────────────────────────────
@app.post("/feedback")
async def feedback(req: FeedbackRequest):
    """
    Adjust ArcadeDB edge strengths based on user vote.
    Thumbs up   → strengthen all edges touching this chunk (+0.1, capped at 1.0)
    Thumbs down → weaken   all edges touching this chunk (-0.1, floored at 0.0)
    """
    def process_feedback() -> dict:
        try:
            updated = apply_feedback(req.chunk_id, req.vote)
            print(f"[FEEDBACK] chunk_id={req.chunk_id} vote={req.vote} edges_updated={updated} query={req.query!r}")
            return {"status": "ok", "chunk_id": req.chunk_id, "vote": req.vote, "edges_updated": updated}
        except Exception as e:
            print(f"[FEEDBACK ERROR] {e}")
            return {"status": "error", "detail": str(e)}

    return await run_in_threadpool(process_feedback)

# ── Auth Endpoints ────────────────────────────────────────────────────────────

@app.post("/auth/register")
async def auth_register(req: RegisterRequest):
    try:
        reg_user = register_user(req.name, req.email, req.password, req.dept)
        return {"status": "ok", "user": reg_user}
    
    except ValueError as e:
        return {"status": "error", "detail": str(e)}
    
@app.post("/auth/login")
async def auth_login(req: LoginRequest):
    try:
        result = login_user(req.email, req.password)
        return {"status": "ok", "user": result["user"], "token": result["token"]}
    except ValueError as e:
        return {"status": "error", "detail": str(e)}

@app.get("/auth/me")
async def auth_me(token: str):
    user = get_user_by_token(token)
    if not user:
        return {"status": "error", "detail": "Invalid or expired token"}
    return {"status": "ok", "user": user}

@app.post("/auth/logout")
async def auth_logout(req: LogoutRequest):
    logout_user(req.token)
    return {"status": "ok"}

@app.get("/auth/users")
async def auth_users():
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT id, name, email, role, dept, avatar, created_at, last_login FROM rag.users ORDER BY id")
                rows = cur.fetchall()
                users = [{"id":r[0],"name":r[1],"email":r[2],"role":r[3],"dept":r[4],"avatar":r[5]} for r in rows]
                return {"status":"ok","users":users}
    except Exception as e:
        return {"status":"error","detail":str(e)}