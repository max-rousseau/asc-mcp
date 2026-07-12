"""App Store Connect API credentials, read from the environment at import time.

Every value is required. There are no defaults and no fallbacks: a missing or
empty variable, or a private key that fails to base64-decode or does not look
like PEM, is a fatal startup error.
"""

from __future__ import annotations

import base64
import binascii
import os

_HELP = "Copy .env.example to .env and fill in required values"


def _require(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. {_HELP}")
    return value


def _require_private_key() -> str:
    """Decode ASC_PRIVATE_KEY_B64 into the PEM text of the .p8 EC private key."""
    raw = _require("ASC_PRIVATE_KEY_B64")
    try:
        pem = base64.b64decode(raw, validate=True).decode("utf-8")
    except (binascii.Error, ValueError, UnicodeDecodeError):
        raise RuntimeError(
            f"ASC_PRIVATE_KEY_B64 is not valid base64. {_HELP}"
        )
    if "-----BEGIN" not in pem:
        raise RuntimeError(
            f"ASC_PRIVATE_KEY_B64 does not decode to a PEM private key. {_HELP}"
        )
    return pem


class Config:
    """Validated App Store Connect credentials."""

    def __init__(self) -> None:
        self.key_id: str = _require("ASC_KEY_ID")
        self.issuer_id: str = _require("ASC_ISSUER_ID")
        self.private_key: str = _require_private_key()


# Validated once at import; fails fast on misconfiguration.
config = Config()
