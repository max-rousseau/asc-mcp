"""Tests for asc_feedback_mcp.config: fatal validation of ASC_* env vars."""

from __future__ import annotations

import base64

import pytest


class TestMissingVariables:
    def test_missing_key_id_is_fatal(self, monkeypatch, valid_env, import_config):
        monkeypatch.delenv("ASC_KEY_ID", raising=False)
        with pytest.raises(RuntimeError, match="ASC_KEY_ID is not set"):
            import_config()

    def test_missing_issuer_id_is_fatal(self, monkeypatch, valid_env, import_config):
        monkeypatch.delenv("ASC_ISSUER_ID", raising=False)
        with pytest.raises(RuntimeError, match="ASC_ISSUER_ID is not set"):
            import_config()

    def test_missing_private_key_is_fatal(self, monkeypatch, valid_env, import_config):
        monkeypatch.delenv("ASC_PRIVATE_KEY_B64", raising=False)
        with pytest.raises(RuntimeError, match="ASC_PRIVATE_KEY_B64 is not set"):
            import_config()

    def test_empty_string_is_treated_as_missing(
        self, monkeypatch, valid_env, import_config
    ):
        monkeypatch.setenv("ASC_KEY_ID", "")
        with pytest.raises(RuntimeError, match="ASC_KEY_ID is not set"):
            import_config()

    def test_missing_var_error_points_to_env_example(
        self, monkeypatch, valid_env, import_config
    ):
        monkeypatch.delenv("ASC_ISSUER_ID", raising=False)
        with pytest.raises(RuntimeError, match=r"Copy \.env\.example to \.env"):
            import_config()


class TestPrivateKeyValidation:
    def test_invalid_base64_is_fatal(self, monkeypatch, valid_env, import_config):
        monkeypatch.setenv("ASC_PRIVATE_KEY_B64", "not-valid-base64!!!")
        with pytest.raises(RuntimeError, match="not valid base64"):
            import_config()

    def test_valid_base64_non_pem_is_fatal(self, monkeypatch, valid_env, import_config):
        monkeypatch.setenv(
            "ASC_PRIVATE_KEY_B64", base64.b64encode(b"just some plain text").decode()
        )
        with pytest.raises(RuntimeError, match="does not decode to a PEM private key"):
            import_config()


class TestHappyPath:
    def test_loads_valid_config(self, valid_env, import_config):
        module = import_config()
        assert module.config.key_id == valid_env["key_id"]
        assert module.config.issuer_id == valid_env["issuer_id"]
        assert module.config.private_key == valid_env["private_key_pem"]

    def test_private_key_contains_pem_header(self, valid_env, import_config):
        module = import_config()
        assert "-----BEGIN" in module.config.private_key
