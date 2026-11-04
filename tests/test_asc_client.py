"""Tests for asc_feedback_mcp.asc_client: JWT minting and API calls."""

from __future__ import annotations

import time

import httpx
import jwt
import pytest


@pytest.fixture
def asc_client_module(valid_env, import_asc_client):
    return import_asc_client()


class TestBearerToken:
    def test_mints_token_with_expected_header_and_payload(
        self, asc_client_module, valid_env, ec_key
    ):
        client = asc_client_module.AscClient()
        token = client._bearer_token()

        header = jwt.get_unverified_header(token)
        assert header["alg"] == "ES256"
        assert header["typ"] == "JWT"
        assert header["kid"] == valid_env["key_id"]

        public_key = ec_key.public_key()
        payload = jwt.decode(
            token, public_key, algorithms=["ES256"], audience="appstoreconnect-v1"
        )
        assert payload["iss"] == valid_env["issuer_id"]
        assert payload["aud"] == "appstoreconnect-v1"
        assert payload["exp"] - payload["iat"] == 1200

    def test_caches_token_within_lifetime(self, asc_client_module):
        client = asc_client_module.AscClient()
        first = client._bearer_token()
        second = client._bearer_token()
        assert first == second

    def test_remints_token_near_expiry(self, asc_client_module):
        client = asc_client_module.AscClient()
        first = client._bearer_token()
        # Simulate the cached token being within the renew-skew window.
        client._token_exp = time.time() + 30
        second = client._bearer_token()
        assert second != first

    def test_does_not_remint_well_before_expiry(self, asc_client_module):
        client = asc_client_module.AscClient()
        first = client._bearer_token()
        client._token_exp = time.time() + 600
        second = client._bearer_token()
        assert second == first


class TestGetHelper:
    async def test_get_success_returns_json_and_sends_bearer_auth(
        self, asc_client_module, mock_transport
    ):
        captured = {}

        def handler(request):
            captured["request"] = request
            return httpx.Response(200, json={"ok": True})

        mock_transport(handler)
        client = asc_client_module.AscClient()

        result = await client._get("/v1/test")

        assert result == {"ok": True}
        request = captured["request"]
        assert str(request.url) == f"{asc_client_module.API_BASE}/v1/test"
        assert request.headers["authorization"].startswith("Bearer ")

    async def test_get_error_raises_asc_api_error(
        self, asc_client_module, mock_transport
    ):
        def handler(request):
            return httpx.Response(404, text="not found")

        mock_transport(handler)
        client = asc_client_module.AscClient()

        with pytest.raises(asc_client_module.AscApiError) as exc_info:
            await client._get("/v1/missing")

        assert exc_info.value.status_code == 404
        assert "not found" in exc_info.value.body
        assert exc_info.value.url == f"{asc_client_module.API_BASE}/v1/missing"

    async def test_get_server_error_raises_asc_api_error(
        self, asc_client_module, mock_transport
    ):
        def handler(request):
            return httpx.Response(500, text="boom")

        mock_transport(handler)
        client = asc_client_module.AscClient()

        with pytest.raises(asc_client_module.AscApiError) as exc_info:
            await client._get("/v1/broken")

        assert exc_info.value.status_code == 500


class TestEndpointConstruction:
    async def test_list_screenshot_feedback_url(
        self, asc_client_module, mock_transport
    ):
        captured = {}

        def handler(request):
            captured["url"] = request.url
            return httpx.Response(200, json={"data": []})

        mock_transport(handler)
        client = asc_client_module.AscClient()

        await client.list_screenshot_feedback("123456", 25)

        url = captured["url"]
        assert url.path == "/v1/apps/123456/betaFeedbackScreenshotSubmissions"
        params = url.params
        assert params["sort"] == "-createdDate"
        assert params["limit"] == "25"
        assert params["include"] == "build"
        assert (
            params["fields[betaFeedbackScreenshotSubmissions]"]
            == asc_client_module._SCREENSHOT_FIELDS
        )

    async def test_list_crash_feedback_url(self, asc_client_module, mock_transport):
        captured = {}

        def handler(request):
            captured["url"] = request.url
            return httpx.Response(200, json={"data": []})

        mock_transport(handler)
        client = asc_client_module.AscClient()

        await client.list_crash_feedback("999", 10)

        url = captured["url"]
        assert url.path == "/v1/apps/999/betaFeedbackCrashSubmissions"
        params = url.params
        assert params["sort"] == "-createdDate"
        assert params["limit"] == "10"
        assert params["include"] == "build"
        assert "fields[betaFeedbackScreenshotSubmissions]" not in params

    async def test_get_crash_log_url(self, asc_client_module, mock_transport):
        captured = {}

        def handler(request):
            captured["url"] = request.url
            return httpx.Response(200, json={"data": {}})

        mock_transport(handler)
        client = asc_client_module.AscClient()

        await client.get_crash_log("abc-123")

        url = captured["url"]
        assert str(url) == (
            f"{asc_client_module.API_BASE}/v1/betaFeedbackCrashSubmissions/abc-123/crashLog"
        )


class TestModuleSingleton:
    def test_module_exposes_a_client_singleton(self, asc_client_module):
        assert isinstance(asc_client_module.client, asc_client_module.AscClient)
