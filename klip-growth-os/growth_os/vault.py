"""Encryption at rest for OAuth tokens.

The key comes from GROWTH_OS_SECRET_KEY (a Fernet key) or, failing that, a
0600 key file created next to the database. Tokens are never logged and never
leave this module in plaintext except to the connector that needs them.
"""

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken

from growth_os.db import DATA_DIR

KEY_FILE = DATA_DIR / ".secret.key"


def _fernet() -> Fernet:
    key = os.environ.get("GROWTH_OS_SECRET_KEY")
    if not key:
        KEY_FILE.parent.mkdir(parents=True, exist_ok=True)
        if not KEY_FILE.exists():
            fd = os.open(KEY_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "wb") as f:
                f.write(Fernet.generate_key())
        key = KEY_FILE.read_bytes().strip()
    return Fernet(key)


def seal(obj: dict) -> bytes:
    return _fernet().encrypt(json.dumps(obj).encode())


def unseal(blob: bytes) -> dict:
    try:
        return json.loads(_fernet().decrypt(blob))
    except InvalidToken as e:
        raise RuntimeError("credential cannot be decrypted with the current key") from e


def redact(obj):
    """Drop token-like fields before anything is logged or exported."""
    if isinstance(obj, dict):
        return {
            k: ("[redacted]" if any(s in k.lower() for s in ("token", "secret", "code", "verifier")) else redact(v))
            for k, v in obj.items()
        }
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def load_client(platform: str) -> dict | None:
    """OAuth client config (the owner's own Google Cloud desktop client).

    Read from env or data/<platform>_client.json, never from the repo.
    """
    env = {
        "youtube": ("GOOGLE_OAUTH_CLIENT_ID", "GOOGLE_OAUTH_CLIENT_SECRET"),
    }.get(platform)
    if env and os.environ.get(env[0]):
        return {"client_id": os.environ[env[0]], "client_secret": os.environ.get(env[1], "")}
    path = DATA_DIR / f"{platform}_client.json"
    if path.exists():
        raw = json.loads(path.read_text())
        raw = raw.get("installed") or raw.get("web") or raw  # Google's download format
        return {"client_id": raw["client_id"], "client_secret": raw.get("client_secret", "")}
    return None
