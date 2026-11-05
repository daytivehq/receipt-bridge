"""A shared secret volume connects the bridge to its isolated runner."""

from __future__ import annotations

import os
import secrets
from pathlib import Path


def runner_token(*, create=False):
    explicit_file = os.getenv("AI_RUNNER_TOKEN_FILE")
    if explicit_file:
        return Path(explicit_file).read_text().strip()
    explicit = os.getenv("AI_RUNNER_TOKEN", "")
    if explicit:
        return explicit
    directory = os.getenv("AI_RUNNER_AUTH_DIR")
    if not directory:
        return ""
    path = Path(directory) / "token"
    if create:
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, "w") as stream:
                stream.write(secrets.token_urlsafe(48))
    with os.fdopen(os.open(path, os.O_RDONLY | os.O_NOFOLLOW)) as stream:
        return stream.read(257).strip()
