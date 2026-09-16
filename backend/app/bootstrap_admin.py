from __future__ import annotations

import argparse
import getpass

from app.database import Database
from app.services.auth import AuthError, AuthService


def main() -> int:
    parser = argparse.ArgumentParser(description="Create StoryStudio's first administrator")
    parser.add_argument("--username", default="Omega")
    args = parser.parse_args()
    db = Database()
    db.initialize()
    auth = AuthService(db)
    if auth.has_users():
        print("StoryStudio already has user accounts; use the Users workspace instead.")
        return 1
    password = getpass.getpass("Initial administrator password: ")
    confirmation = getpass.getpass("Confirm password: ")
    if password != confirmation:
        print("Passwords do not match.")
        return 1
    try:
        user = auth.create_user(args.username, password, "admin")
    except AuthError as exc:
        print(str(exc))
        return 1
    db.execute("UPDATE story_nodes SET author_user_id=?,author_name_snapshot=? WHERE (role='user' OR action_kind='manual_story') AND author_user_id IS NULL", (user["id"], user["username"]))
    db.execute("UPDATE generation_jobs SET requested_by_user_id=?,requester_name_snapshot=? WHERE requested_by_user_id IS NULL", (user["id"], user["username"]))
    print(f"Administrator {user['username']} created. Start StoryStudio and sign in.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
