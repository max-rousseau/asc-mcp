"""Shared fixtures for the asc-feedback-mcp test suite.

Isolation notes:
- config.py, asc_client.py and server.py all execute module-level code on
  import (Config()/AscClient() singletons, FastMCP(...) instance) that reads
  os.environ. Tests therefore set env vars with monkeypatch *before* forcing a
  fresh import (clearing sys.modules), never touching the real .env.
- FastMCP's Settings loads a relative ".env" file on construction. Every test
  chdir's into tmp_path first so that relative path never resolves to the
  project's real .env file.
"""

from __future__ import annotations

import base64
import importlib
import sys

import httpx
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

CONFIG_MODULE = "asc_feedback_mcp.config"
ASC_CLIENT_MODULE = "asc_feedback_mcp.asc_client"
SERVER_MODULE = "asc_feedback_mcp.server"

_ALL_MODULES = (CONFIG_MODULE, ASC_CLIENT_MODULE, SERVER_MODULE)


@pytest.fixture(autouse=True)
def isolated_cwd(monkeypatch, tmp_path):
    """Run every test from an isolated directory with no real .env present."""
    monkeypatch.chdir(tmp_path)


@pytest.fixture(autouse=True)
def clean_module_cache():
    """Ensure config/asc_client/server are freshly imported for every test."""
    for name in _ALL_MODULES:
        sys.modules.pop(name, None)
    yield
    for name in _ALL_MODULES:
        sys.modules.pop(name, None)


@pytest.fixture
def ec_key():
    """A throwaway EC P-256 private key object, generated fresh per test."""
    return ec.generate_private_key(ec.SECP256R1())


@pytest.fixture
def valid_env(monkeypatch, ec_key):
    """Set valid dummy ASC_* env vars backed by a real throwaway EC key."""
    pem = ec_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    b64 = base64.b64encode(pem).decode()
    key_id = "TESTKEYID1"
    issuer_id = "11111111-2222-3333-4444-555555555555"
    monkeypatch.setenv("ASC_KEY_ID", key_id)
    monkeypatch.setenv("ASC_ISSUER_ID", issuer_id)
    monkeypatch.setenv("ASC_PRIVATE_KEY_B64", b64)
    return {
        "key_id": key_id,
        "issuer_id": issuer_id,
        "private_key_pem": pem.decode(),
        "private_key_b64": b64,
    }


def _fresh_import(name: str, *deps: str):
    for dep in deps:
        sys.modules.pop(dep, None)
    sys.modules.pop(name, None)
    return importlib.import_module(name)


@pytest.fixture
def import_config():
    def _do():
        return _fresh_import(CONFIG_MODULE)

    return _do


@pytest.fixture
def import_asc_client():
    def _do():
        return _fresh_import(ASC_CLIENT_MODULE, CONFIG_MODULE)

    return _do


@pytest.fixture
def import_server():
    def _do():
        return _fresh_import(SERVER_MODULE, CONFIG_MODULE, ASC_CLIENT_MODULE)

    return _do


@pytest.fixture
def mock_transport(monkeypatch):
    """Patch httpx.AsyncClient so every instance uses a MockTransport.

    Returns a function that, given a handler(request) -> httpx.Response,
    installs it and returns the underlying httpx.MockTransport.
    """
    original_async_client = httpx.AsyncClient

    def _install(handler):
        transport = httpx.MockTransport(handler)

        def factory(*args, **kwargs):
            kwargs["transport"] = transport
            return original_async_client(*args, **kwargs)

        monkeypatch.setattr(httpx, "AsyncClient", factory)
        return transport

    return _install
