"""Account rules: pure checks shared by registration and login (no I/O)."""

import re

from app.shared.errors import GameError

USERNAME_RE = re.compile(r"^[A-Za-z0-9_]{3,32}$")
PASSWORD_MIN = 10
PASSWORD_MAX = 128  # caps hashing cost


def normalize_username(username: str) -> str:
    return username.strip().lower()


def check_username(username: str) -> str:
    username = username.strip()
    if not USERNAME_RE.fullmatch(username):
        raise GameError("auth.username_invalid", 400)
    return username


def check_password(password: str) -> str:
    if not PASSWORD_MIN <= len(password) <= PASSWORD_MAX:
        raise GameError("auth.password_invalid", 400)
    return password
