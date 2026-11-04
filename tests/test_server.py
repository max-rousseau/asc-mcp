"""Tests for asc_feedback_mcp.server: tool validation and tool behavior."""

from __future__ import annotations

import base64

import httpx
import pytest


@pytest.fixture
def server_module(valid_env, import_server):
    return import_server()


def _fail_on_request(request):
    pytest.fail(f"unexpected request: {request.url}")


class TestAppIdValidation:
    @pytest.mark.parametrize(
        "bad_id",
        ["", "abc", "12a", "12 3", "-123", "123.0", "123\n", "١٢٣", "１２３"],
    )
    @pytest.mark.parametrize(
        "tool", ["list_screenshot_feedback", "list_crash_feedback"]
    )
    async def test_rejects_non_digit_app_ids(
        self, server_module, mock_transport, tool, bad_id
    ):
        mock_transport(_fail_on_request)
        with pytest.raises(ValueError, match="asc_app_id must contain digits only"):
            await getattr(server_module, tool)(bad_id)

    async def test_accepts_digits_only_app_id(self, server_module, mock_transport):
        def handler(request):
            return httpx.Response(200, json={"data": []})

        mock_transport(handler)
        result = await server_module.list_screenshot_feedback("123456789")
        assert result == {"data": []}


class TestLimitValidation:
    @pytest.mark.parametrize("bad_limit", [0, -1, 201, 1000])
    @pytest.mark.parametrize(
        "tool", ["list_screenshot_feedback", "list_crash_feedback"]
    )
    async def test_rejects_out_of_bounds_limit(
        self, server_module, mock_transport, tool, bad_limit
    ):
        mock_transport(_fail_on_request)
        with pytest.raises(
            ValueError, match="limit must be between 1 and 200 inclusive"
        ):
            await getattr(server_module, tool)("123", limit=bad_limit)

    @pytest.mark.parametrize("good_limit", [1, 50, 200])
    async def test_accepts_boundary_limits(
        self, server_module, mock_transport, good_limit
    ):
        def handler(request):
            return httpx.Response(200, json={"data": []})

        mock_transport(handler)
        result = await server_module.list_crash_feedback("123", limit=good_limit)
        assert result == {"data": []}


class TestSubmissionIdValidation:
    @pytest.mark.parametrize(
        "bad_id",
        [
            "",
            "has space",
            "slash/es",
            "..",
            ".",
            "a.b",
            "semi;colon",
            "abc\n",
            "a/../b",
            "a[b",
            "a]b",
            "a^b",
            "a\\b",
            "a`b",
            "café",
            "٣",
            "ａbc",
        ],
    )
    async def test_rejects_invalid_charset(self, server_module, mock_transport, bad_id):
        mock_transport(_fail_on_request)
        with pytest.raises(
            ValueError,
            match="submission_id may only contain letters, digits, dashes, and underscores",
        ):
            await server_module.get_crash_log(bad_id)

    @pytest.mark.parametrize(
        "good_id",
        [
            "abc-123-XYZ",
            "ADfioBtLMn4BqZoD9y_ucEQ",
            "APz_4CxdJoSQ6MLPnmnTJAk",
            "AKv444oGBysK_YwgKN3hPfU",
            "AGeT82VVL7u-zyANyb2sy4Q",
            "ABS1sLYZdPCaPGNC7sJpP7E",
            "_leading",
            "trailing_",
            "___",
            "a___b",
        ],
    )
    async def test_accepts_alnum_dash_and_underscore(
        self, server_module, mock_transport, good_id
    ):
        def handler(request):
            return httpx.Response(200, json={"data": {}})

        mock_transport(handler)
        result = await server_module.get_crash_log(good_id)
        assert result == {"data": {}}


class TestListScreenshotFeedbackToolHappyPath:
    async def test_returns_api_json(self, server_module, mock_transport):
        captured = {}

        def handler(request):
            captured["url"] = request.url
            return httpx.Response(200, json={"data": [{"id": "1"}]})

        mock_transport(handler)
        result = await server_module.list_screenshot_feedback("42", limit=5)

        assert result == {"data": [{"id": "1"}]}
        assert captured["url"].path == "/v1/apps/42/betaFeedbackScreenshotSubmissions"

    async def test_propagates_api_error(self, server_module, mock_transport):
        def handler(request):
            return httpx.Response(403, text="forbidden")

        mock_transport(handler)
        with pytest.raises(Exception, match="forbidden"):
            await server_module.list_screenshot_feedback("42")


class TestListCrashFeedbackToolHappyPath:
    async def test_returns_api_json(self, server_module, mock_transport):
        def handler(request):
            return httpx.Response(200, json={"data": [{"id": "crash-1"}]})

        mock_transport(handler)
        result = await server_module.list_crash_feedback("42", limit=5)
        assert result == {"data": [{"id": "crash-1"}]}


class TestGetCrashLogToolHappyPath:
    async def test_returns_api_json(self, server_module, mock_transport):
        def handler(request):
            return httpx.Response(
                200, json={"data": {"attributes": {"logText": "boom"}}}
            )

        mock_transport(handler)
        result = await server_module.get_crash_log("crash-1")
        assert result["data"]["attributes"]["logText"] == "boom"


class TestDownloadScreenshotValidation:
    async def test_rejects_non_https_scheme(self, server_module, mock_transport):
        mock_transport(_fail_on_request)
        with pytest.raises(ValueError, match="url must be an https URL"):
            await server_module.download_screenshot(
                "http://developer.apple.com/shot.png"
            )

    async def test_rejects_non_apple_host(self, server_module, mock_transport):
        mock_transport(_fail_on_request)
        with pytest.raises(
            ValueError, match="url host is not an Apple-controlled domain"
        ):
            await server_module.download_screenshot("https://evil.example.com/shot.png")

    @pytest.mark.parametrize(
        "url",
        [
            "https://developer.apple.com/shot.png",
            "https://screenshots.mzstatic.com/shot.png",
            "https://feedback.icloud.com/shot.png",
        ],
    )
    async def test_accepts_apple_owned_hosts(self, server_module, mock_transport, url):
        def handler(request):
            return httpx.Response(
                200, content=b"\x89PNG\r\n", headers={"Content-Type": "image/png"}
            )

        mock_transport(handler)
        image = await server_module.download_screenshot(url)
        assert image.data == b"\x89PNG\r\n"

    async def test_refuses_to_follow_redirect(self, server_module, mock_transport):
        def handler(request):
            return httpx.Response(
                302, headers={"Location": "https://evil.example.com/shot.png"}
            )

        mock_transport(handler)
        with pytest.raises(ValueError, match="refusing to follow redirect"):
            await server_module.download_screenshot(
                "https://developer.apple.com/shot.png"
            )

    async def test_raises_on_http_error_status(self, server_module, mock_transport):
        def handler(request):
            return httpx.Response(404, text="not found")

        mock_transport(handler)
        with pytest.raises(httpx.HTTPStatusError):
            await server_module.download_screenshot(
                "https://developer.apple.com/shot.png"
            )


class TestDownloadScreenshotHappyPath:
    async def test_returns_image_with_content_and_format(
        self, server_module, mock_transport
    ):
        png_bytes = b"\x89PNG\r\n\x1a\nfakecontent"

        def handler(request):
            return httpx.Response(
                200, content=png_bytes, headers={"Content-Type": "image/png"}
            )

        mock_transport(handler)
        image = await server_module.download_screenshot(
            "https://developer.apple.com/shot.png"
        )

        assert image.data == png_bytes
        content = image.to_image_content()
        assert content.mimeType == "image/png"
        assert base64.b64decode(content.data) == png_bytes

    async def test_defaults_to_png_when_no_content_type(
        self, server_module, mock_transport
    ):
        def handler(request):
            return httpx.Response(200, content=b"rawbytes")

        mock_transport(handler)
        image = await server_module.download_screenshot(
            "https://developer.apple.com/shot.png"
        )

        assert image.to_image_content().mimeType == "image/png"

    async def test_strips_charset_from_content_type(
        self, server_module, mock_transport
    ):
        def handler(request):
            return httpx.Response(
                200,
                content=b"rawbytes",
                headers={"Content-Type": "image/jpeg; charset=binary"},
            )

        mock_transport(handler)
        image = await server_module.download_screenshot(
            "https://developer.apple.com/shot.png"
        )

        assert image.to_image_content().mimeType == "image/jpeg"


class TestServerModule:
    def test_exposes_fastmcp_instance(self, server_module):
        from mcp.server.fastmcp import FastMCP

        assert isinstance(server_module.mcp, FastMCP)
