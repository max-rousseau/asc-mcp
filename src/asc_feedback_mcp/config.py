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
    """Read a required environment variable, failing fast if it is unset.

    Args:
        name: The environment variable name to look up.

    Returns:
        The variable's value.

    Raises:
        RuntimeError: If the variable is unset or empty.
    """
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"{name} is not set. {_HELP}")
    return value


def _require_private_key() -> str:
    """Decode ASC_PRIVATE_KEY_B64 into the PEM text of the .p8 EC private key.

    Returns:
        The decoded PEM-encoded EC private key text.

    Raises:
        RuntimeError: If ``ASC_PRIVATE_KEY_B64`` is unset, is not valid
            base64, or does not decode to PEM content.
    """
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
    """Validated App Store Connect credentials, loaded from the environment.

    Attributes:
        key_id: The App Store Connect API key id (``ASC_KEY_ID``).
        issuer_id: The App Store Connect issuer id (``ASC_ISSUER_ID``).
        private_key: PEM text of the ``.p8`` EC private key, decoded from
            ``ASC_PRIVATE_KEY_B64``.

    Raises:
        RuntimeError: If any required environment variable is missing or
            invalid.
    """

    def __init__(self) -> None:
        """Read and validate all required credentials from the environment."""
        self.key_id: str = _require("ASC_KEY_ID")
        self.issuer_id: str = _require("ASC_ISSUER_ID")
        self.private_key: str = _require_private_key()


# Validated once at import; fails fast on misconfiguration.
config = Config()
