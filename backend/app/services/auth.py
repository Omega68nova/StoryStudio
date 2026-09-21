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
from app.data.dataProvider import DataProvider

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
    def __init__(
        self,
        db: Database,
        *,
        data_provider: DataProvider | None = None,
    ) -> None:
        self.db = db
        self.data = data_provider or DataProvider(db)
        self.repo = self.data.auth
        self.limiter = LoginLimiter()

    @staticmethod
    def normalize_username(username: str) -> str:
        return " ".join(username.strip().split()).casefold()

    @staticmethod
    def validate_username(username: str) -> str:
        value = " ".join(username.strip().split())
        if not USERNAME_RE.fullmatch(value):
            raise AuthError(
                "Username must be 3-32 characters using letters, numbers, "
                "spaces, dot, underscore, or hyphen"
            )
        return value

    @staticmethod
    def validate_password(password: str) -> None:
        if not 8 <= len(password) <= 128:
            raise AuthError("Password must be between 8 and 128 characters")

    def has_users(self) -> bool:
        return self.repo.has_users()

    def create_user(
        self,
        username: str,
        password: str,
        role: str = "member",
    ) -> dict[str, Any]:
        username = self.validate_username(username)
        self.validate_password(password)
        if role not in {"admin", "member"}:
            raise AuthError("Invalid account role")
        user_id = new_id()
        try:
            row = self.repo.create_user(
                user_id=user_id,
                username=username,
                normalized_username=self.normalize_username(username),
                password_hash=_hasher.hash(password),
                role=role,
            )
        except Exception as exc:
            if "UNIQUE" in str(exc):
                raise AuthError("That username already exists") from exc
            raise
        return self.public_user(row)

    @staticmethod
    def public_user(row: dict[str, Any]) -> dict[str, Any]:
        return {
            key: row.get(key)
            for key in (
                "id", "username", "role", "enabled", "created_at",
                "updated_at", "last_login_at",
            )
        }

    def authenticate(
        self,
        username: str,
        password: str,
        client_key: str,
    ) -> tuple[dict[str, Any], str]:
        key = f"{client_key}:{self.normalize_username(username)}"
        self.limiter.check(key)
        row = self.repo.user_by_normalized_username(
            self.normalize_username(username)
        )
        try:
            valid = bool(
                row
                and row["enabled"]
                and _hasher.verify(row["password_hash"], password)
            )
        except (VerifyMismatchError, InvalidHashError):
            valid = False
        if not valid:
            self.limiter.fail(key)
            raise AuthError("Invalid username or password")
        self.limiter.clear(key)

        if _hasher.check_needs_rehash(row["password_hash"]):
            self.repo.update_password_hash(
                row["id"],
                _hasher.hash(password),
            )

        token = secrets.token_urlsafe(48)
        now = datetime.now(UTC)
        now_text = now.isoformat()
        self.repo.create_session(
            user_id=row["id"],
            token_hash=self.token_hash(token),
            expires_at=(now + timedelta(days=SESSION_DAYS)).isoformat(),
            created_at=now_text,
        )
        self.repo.set_last_login(row["id"], now_text)
        return self.public_user(row), token

    @staticmethod
    def token_hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def user_for_token(self, token: str | None) -> AuthUser | None:
        if not token:
            return None
        row = self.repo.user_for_token_hash(
            self.token_hash(token),
            utc_now(),
        )
        return AuthUser(row["id"], row["username"], row["role"]) if row else None

    def revoke_token(self, token: str | None) -> None:
        if token:
            self.repo.revoke_token_hash(self.token_hash(token))

    def change_password(self, user_id: str, current: str, new: str) -> None:
        self.validate_password(new)
        password_hash = self.repo.password_hash(user_id)
        try:
            valid = bool(
                password_hash
                and _hasher.verify(password_hash, current)
            )
        except (VerifyMismatchError, InvalidHashError):
            valid = False
        if not valid:
            raise AuthError("Current password is incorrect")
        self.set_password(user_id, new)

    def set_password(self, user_id: str, password: str) -> None:
        self.validate_password(password)
        self.repo.update_password_hash(user_id, _hasher.hash(password))
        self.repo.revoke_user_sessions(user_id)

    def assigned(self, user_id: str, project_id: str) -> bool:
        return self.repo.assigned(user_id, project_id)
