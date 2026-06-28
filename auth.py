import psycopg2
import bcrypt
import secrets
import re
from datetime       import datetime, timedelta
from config         import DB_CONFIG

# ── Simple JWT-like token using secrets ──────────────────────────────────────
# For production use python-jose or PyJWT, but this is secure enough for internal use

TOKEN_EXPIRY_HOURS = 24
_active_tokens: dict = {}  # token -> {user_id, expires_at}

def _hash_password(password: str) -> str:
    """Bcrypt hash — generates unique salt each time."""
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _generate_token(user_id: int) ->str:
    token = secrets.token_hex(32)
    _active_tokens[token] = {
        "user_id": user_id,
        "expires_at": datetime.now() + timedelta(hours=TOKEN_EXPIRY_HOURS)
    }

    return token

def _verify_token(token: str) ->str:
    """Returns user_id if valid, None if expired/invalid."""
    entry = _active_tokens.get(token)
    if not entry: return None
    if datetime.now() > entry["expires_at"]:
        del _active_tokens[token]
        return None
    
    return entry["user_id"]

def _validate_email(email: str) -> bool:
    """Basic email format validation."""
    return bool(re.match(r"^[^@]+@[^@]+\.[^@]+$", email))

def _validate_password(password: str) -> tuple[bool, str]:
    if len(password) < 6: return False, "Password must be at least 6 characters"
    return True, ""

def register_user(name: str, email: str, password: str, department: str = "") -> dict:
    """Register a new user. Returns user dict or raises ValueError."""
    if not name or len(name.strip()) < 2:
        raise ValueError("Name must be at least 2 characters")
    if not _validate_email(email):
        raise ValueError("Invalid email format")
    ok, msg = _validate_password(password)
    if not ok: raise ValueError(msg)

    email = email.strip().lower()
    name = name.strip()

    parts = name.split()

    avatar = (parts[0][0] + (parts[1][0] if len(parts) > 1 else parts[0][1])).upper()

    hashed = _hash_password(password)

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO rag.users (name, email, password, role, dept, avatar)
                    VALUES (%s, %s, %s, 'tech', %s, %s)
                    RETURNING id, name, email, role, dept, avatar, created_at
                """, (name, email, hashed, department, avatar))
                row = cur.fetchone()
                conn.commit()
                return {
                    "id":    row[0],
                    "name":  row[1],
                    "email": row[2],
                    "role":  row[3],
                    "dept":  row[4],
                    "avatar":row[5],
                }
    except psycopg2.errors.UniqueViolation:
        raise ValueError("Email already registered")
    except Exception as e:
        raise ValueError(f"Registration failed: {e}")

    
def login_user(email: str, password: str) -> dict:
    """Login user. Returns {user, token} or raises ValueError."""

    if not email or not password:
        raise ValueError("Email and password required")
    
    email = email.strip().lower()

    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                # Fetch user including hashed password
                cur.execute("""
                    SELECT id, name, email, role, dept, avatar, password
                    FROM rag.users
                    WHERE email = %s
                """, (email,))
                row = cur.fetchone()

                # Verify password using bcrypt
                if not row or not bcrypt.checkpw(password.encode(), row[6].encode()):
                    raise ValueError("Invalid email or password")

                # Update last_login
                cur.execute("""
                    UPDATE rag.users SET last_login = now() WHERE id = %s
                """, (row[0],))
                conn.commit()

                user = {
                    "id":     row[0],
                    "name":   row[1],
                    "email":  row[2],
                    "role":   row[3],
                    "dept":   row[4],
                    "avatar": row[5],
                }
                token = _generate_token(row[0])
                return {"user": user, "token": token}

    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Login failed: {e}")
        
def get_user_by_token(token: str) ->dict | None:
    """Returns user dict if token is valid, None otherwise."""
    user_id = _verify_token(token)
    if not user_id: return None
    try:
        with psycopg2.connect(**DB_CONFIG) as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    SELECT id, name, email, role, dept, avatar
                    FROM rag.users WHERE id = %s
                """, (user_id,))
                row = cur.fetchone()
                if not row:
                    return None
                return {
                    "id":    row[0],
                    "name":  row[1],
                    "email": row[2],
                    "role":  row[3],
                    "dept":  row[4],
                    "avatar":row[5],
                }
    except:
        return None
    
def logout_user(token: str) ->bool:
    if token in _active_tokens:
        del _active_tokens[token]
        return True
    return False

