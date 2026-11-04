"""Single administrator password: salted scrypt hash, no plaintext password storage."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets


def password_hash(password: str) -> dict:
    if not isinstance(password, str) or not 12 <= len(password) <= 1024:
        raise ValueError("관리 비밀번호는 12자 이상, 1,024자 이하로 입력하세요")
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
    return {"version": 1, "salt": base64.b64encode(salt).decode(), "hash": base64.b64encode(digest).decode()}


def password_matches(password, record) -> bool:
    if not isinstance(password, str) or len(password) > 1024 or not record:
        return False
    try:
        salt = base64.b64decode(record["salt"], validate=True)
        expected = base64.b64decode(record["hash"], validate=True)
        if record["version"] != 1 or len(salt) != 16 or len(expected) != 32:
            return False
        digest = hashlib.scrypt(password.encode(), salt=salt, n=16384, r=8, p=1, dklen=32)
        return hmac.compare_digest(digest, expected)
    except (KeyError, ValueError, TypeError):
        return False
