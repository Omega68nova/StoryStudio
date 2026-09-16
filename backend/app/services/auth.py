from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError

from app.database import Database, new_id, utc_now


COOKIE_NAME = "storystudio_session"
SESSION_DAYS = 7
USERNAME_RE = re.compile(r"^[A-Za-z0-9_. -]{3,32}$")
_hasher = PasswordHasher()


@dataclass(frozen=True)
class AuthUser:
    id: str
    username: str
    role: str

    @property
    def admin(self) -> bool:
        return self.role == "admin"


class AuthError(ValueError):
    pass


class LoginLimiter:
    def __init__(self) -> None:
        self.attempts: dict[str, list[float]] = {}

    def check(self, key: str) -> None:
        now = time.monotonic()
        recent = [stamp for stamp in self.attempts.get(key, []) if now - stamp < 900]
        self.attempts[key] = recent
        if len(recent) >= 8:
            raise AuthError("Too many login attempts. Try again later.")

    def fail(self, key: str) -> None:
        self.attempts.setdefault(key, []).append(time.monotonic())

    def clear(self, key: str) -> None:
        self.attempts.pop(key, None)


class AuthService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.limiter = LoginLimiter()

    @staticmethod
    def normalize_username(username: str) -> str:
        return " ".join(username.strip().split()).casefold()

    @staticmethod
    def validate_username(username: str) -> str:
        value = " ".join(username.strip().split())
        if not USERNAME_RE.fullmatch(value):
            raise AuthError("Username must be 3-32 characters using letters, numbers, spaces, dot, underscore, or hyphen")
        return value

    @staticmethod
    def validate_password(password: str) -> None:
        if not 8 <= len(password) <= 128:
            raise AuthError("Password must be between 8 and 128 characters")

    def has_users(self) -> bool:
        return bool(self.db.fetch_one("SELECT 1 FROM users LIMIT 1"))

    def create_user(self, username: str, password: str, role: str = "member") -> dict[str, Any]:
        username = self.validate_username(username)
        self.validate_password(password)
        if role not in {"admin", "member"}:
            raise AuthError("Invalid account role")
        now, user_id = utc_now(), new_id()
        try:
            self.db.execute(
                "INSERT INTO users(id,username,username_normalized,password_hash,role,enabled,created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)",
                (user_id, username, self.normalize_username(username), _hasher.hash(password), role, now, now),
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise AuthError("That username already exists") from exc
            raise
        return self.public_user(self.db.fetch_one("SELECT * FROM users WHERE id=?", (user_id,)) or {})

    @staticmethod
    def public_user(row: dict[str, Any]) -> dict[str, Any]:
        return {key: row.get(key) for key in ("id", "username", "role", "enabled", "created_at", "updated_at", "last_login_at")}

    def authenticate(self, username: str, password: str, client_key: str) -> tuple[dict[str, Any], str]:
        key = f"{client_key}:{self.normalize_username(username)}"
        self.limiter.check(key)
        row = self.db.fetch_one("SELECT * FROM users WHERE username_normalized=?", (self.normalize_username(username),))
        try:
            valid = bool(row and row["enabled"] and _hasher.verify(row["password_hash"], password))
        except (VerifyMismatchError, InvalidHashError):
            valid = False
        if not valid:
            self.limiter.fail(key)
            raise AuthError("Invalid username or password")
        self.limiter.clear(key)
        if _hasher.check_needs_rehash(row["password_hash"]):
            self.db.execute("UPDATE users SET password_hash=?,updated_at=? WHERE id=?", (_hasher.hash(password), utc_now(), row["id"]))
        token = secrets.token_urlsafe(48)
        now = datetime.now(UTC)
        self.db.execute(
            "INSERT INTO auth_sessions(id,user_id,token_hash,expires_at,created_at,last_seen_at) VALUES(?,?,?,?,?,?)",
            (new_id(), row["id"], self.token_hash(token), (now + timedelta(days=SESSION_DAYS)).isoformat(), now.isoformat(), now.isoformat()),
        )
        self.db.execute("UPDATE users SET last_login_at=? WHERE id=?", (now.isoformat(), row["id"]))
        return self.public_user(row), token

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def user_for_token(self, token: str | None) -> AuthUser | None:
        if not token:
            return None
        row = self.db.fetch_one(
            "SELECT u.* FROM auth_sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1",
            (self.token_hash(token), utc_now()),
        )
        return AuthUser(row["id"], row["username"], row["role"]) if row else None

    def revoke_token(self, token: str | None) -> None:
        if token:
            self.db.execute("DELETE FROM auth_sessions WHERE token_hash=?", (self.token_hash(token),))

    def change_password(self, user_id: str, current: str, new: str) -> None:
        self.validate_password(new)
        row = self.db.fetch_one("SELECT password_hash FROM users WHERE id=?", (user_id,))
        try:
            valid = bool(row and _hasher.verify(row["password_hash"], current))
        except (VerifyMismatchError, InvalidHashError):
            valid = False
        if not valid:
            raise AuthError("Current password is incorrect")
        self.set_password(user_id, new)

    def set_password(self, user_id: str, password: str) -> None:
        self.validate_password(password)
        self.db.execute("UPDATE users SET password_hash=?,updated_at=? WHERE id=?", (_hasher.hash(password), utc_now(), user_id))
        self.db.execute("DELETE FROM auth_sessions WHERE user_id=?", (user_id,))

    def assigned(self, user_id: str, project_id: str) -> bool:
        return bool(self.db.fetch_one("SELECT 1 FROM user_project_access WHERE user_id=? AND project_id=?", (user_id, project_id)))

