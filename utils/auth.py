import os
import sqlite3
import hashlib
import hmac
import time
from datetime import datetime, timedelta

import jwt

from config import AUTH_DB_PATH, JWT_SECRET, JWT_ALG, JWT_EXP_MINUTES


def init_auth_db():
    os.makedirs(os.path.dirname(AUTH_DB_PATH), exist_ok=True)
    conn = sqlite3.connect(AUTH_DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            username TEXT PRIMARY KEY,
            password_hash TEXT NOT NULL,
            salt TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    conn.commit()
    conn.close()


def _hash_password(password: str, salt_hex: str) -> str:
    raw = (salt_hex + password).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def create_user(username: str, password: str) -> tuple[bool, str]:
    username = (username or "").strip()
    password = (password or "").strip()
    if not username or not password:
        return False, "用户名或密码为空"

    conn = sqlite3.connect(AUTH_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username = ?", (username,))
    if c.fetchone():
        conn.close()
        return False, "账号已存在"

    salt = os.urandom(16).hex()
    pw_hash = _hash_password(password, salt)
    now = datetime.utcnow().isoformat()
    c.execute(
        "INSERT INTO users (username, password_hash, salt, created_at) VALUES (?, ?, ?, ?)",
        (username, pw_hash, salt, now),
    )
    conn.commit()
    conn.close()
    return True, "ok"


def verify_user(username: str, password: str) -> bool:
    username = (username or "").strip()
    password = (password or "").strip()
    conn = sqlite3.connect(AUTH_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT password_hash, salt FROM users WHERE username = ?", (username,))
    row = c.fetchone()
    conn.close()
    if not row:
        return False
    stored_hash, salt = row
    calc = _hash_password(password, salt)
    return hmac.compare_digest(stored_hash, calc)


def reset_password(username: str, old_password: str, new_password: str) -> tuple[bool, str]:
    username = (username or "").strip()
    old_password = (old_password or "").strip()
    new_password = (new_password or "").strip()
    if not username or not new_password:
        return False, "用户名或新密码为空"
    if not verify_user(username, old_password):
        return False, "旧密码不正确"
    salt = os.urandom(16).hex()
    pw_hash = _hash_password(new_password, salt)
    conn = sqlite3.connect(AUTH_DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
        (pw_hash, salt, username),
    )
    conn.commit()
    conn.close()
    return True, "ok"


def list_users() -> list[dict]:
    conn = sqlite3.connect(AUTH_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username, created_at FROM users ORDER BY created_at DESC")
    rows = c.fetchall()
    conn.close()
    return [{"username": r[0], "created_at": r[1]} for r in rows]


def admin_set_password(username: str, new_password: str) -> tuple[bool, str]:
    username = (username or "").strip()
    new_password = (new_password or "").strip()
    if not username or not new_password:
        return False, "用户名或新密码为空"
    conn = sqlite3.connect(AUTH_DB_PATH)
    c = conn.cursor()
    c.execute("SELECT username FROM users WHERE username = ?", (username,))
    if not c.fetchone():
        conn.close()
        return False, "账号不存在"
    salt = os.urandom(16).hex()
    pw_hash = _hash_password(new_password, salt)
    c.execute(
        "UPDATE users SET password_hash = ?, salt = ? WHERE username = ?",
        (pw_hash, salt, username),
    )
    conn.commit()
    conn.close()
    return True, "ok"


def delete_user(username: str) -> tuple[bool, str]:
    username = (username or "").strip()
    if not username:
        return False, "用户名为空"
    conn = sqlite3.connect(AUTH_DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM users WHERE username = ?", (username,))
    conn.commit()
    conn.close()
    return True, "ok"


def issue_token(username: str) -> str:
    exp = datetime.utcnow() + timedelta(minutes=JWT_EXP_MINUTES)
    payload = {"sub": username, "exp": exp}
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALG)


def verify_token(token: str) -> str | None:
    try:
        data = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALG])
        return data.get("sub")
    except Exception:
        return None
