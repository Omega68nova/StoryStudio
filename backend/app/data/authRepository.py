from __future__ import annotations

from typing import Any

from app.data.baseRepository import BaseRepository
from app.database import new_id, utc_now


class AuthRepository(BaseRepository):
    def has_users(self) -> bool:
        return bool(self.db.fetch_one("SELECT 1 FROM users LIMIT 1"))

    def user(self, user_id: str) -> dict[str, Any] | None:
        return self.db.fetch_one("SELECT * FROM users WHERE id=?", (user_id,))

    def user_by_normalized_username(
        self,
        normalized: str,
    ) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT * FROM users WHERE username_normalized=?",
            (normalized,),
        )

    def create_user(
        self,
        *,
        user_id: str,
        username: str,
        normalized_username: str,
        password_hash: str,
        role: str,
    ) -> dict[str, Any]:
        now = utc_now()
        self.db.execute(
            "INSERT INTO users"
            "(id,username,username_normalized,password_hash,role,enabled,"
            "created_at,updated_at) VALUES(?,?,?,?,?,1,?,?)",
            (
                user_id,
                username,
                normalized_username,
                password_hash,
                role,
                now,
                now,
            ),
        )
        return self.user(user_id) or {}

    def update_password_hash(
        self,
        user_id: str,
        password_hash: str,
    ) -> None:
        self.db.execute(
            "UPDATE users SET password_hash=?,updated_at=? WHERE id=?",
            (password_hash, utc_now(), user_id),
        )

    def password_hash(self, user_id: str) -> str | None:
        row = self.db.fetch_one(
            "SELECT password_hash FROM users WHERE id=?",
            (user_id,),
        )
        return str(row["password_hash"]) if row else None

    def create_session(
        self,
        *,
        user_id: str,
        token_hash: str,
        expires_at: str,
        created_at: str,
    ) -> None:
        self.db.execute(
            "INSERT INTO auth_sessions"
            "(id,user_id,token_hash,expires_at,created_at,last_seen_at) "
            "VALUES(?,?,?,?,?,?)",
            (
                new_id(),
                user_id,
                token_hash,
                expires_at,
                created_at,
                created_at,
            ),
        )

    def user_for_token_hash(
        self,
        token_hash: str,
        now: str,
    ) -> dict[str, Any] | None:
        return self.db.fetch_one(
            "SELECT u.* FROM auth_sessions s "
            "JOIN users u ON u.id=s.user_id "
            "WHERE s.token_hash=? AND s.expires_at>? AND u.enabled=1",
            (token_hash, now),
        )

    def revoke_token_hash(self, token_hash: str) -> None:
        self.db.execute(
            "DELETE FROM auth_sessions WHERE token_hash=?",
            (token_hash,),
        )

    def revoke_user_sessions(self, user_id: str) -> None:
        self.db.execute(
            "DELETE FROM auth_sessions WHERE user_id=?",
            (user_id,),
        )

    def set_last_login(self, user_id: str, timestamp: str) -> None:
        self.db.execute(
            "UPDATE users SET last_login_at=? WHERE id=?",
            (timestamp, user_id),
        )

    def assigned(self, user_id: str, project_id: str) -> bool:
        return bool(self.db.fetch_one(
            "SELECT 1 FROM user_project_access "
            "WHERE user_id=? AND project_id=?",
            (user_id, project_id),
        ))
