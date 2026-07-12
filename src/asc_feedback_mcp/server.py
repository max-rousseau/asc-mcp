"""FastMCP server exposing App Store Connect TestFlight beta feedback tools.

Binds to 0.0.0.0:8080 with the streamable-http transport (endpoint /mcp).
Run with: python -m asc_feedback_mcp.server
"""

from __future__ import annotations

import re

import httpx
from mcp.server.fastmcp import FastMCP, Image

from .asc_client import client

mcp = FastMCP("asc-feedback", host="0.0.0.0", port=8080)

_APP_ID_RE = re.compile(r"^\d+$")
_SUBMISSION_ID_RE = re.compile(r"^[A-Za-z0-9-]+$")
# Apple-controlled download hosts. Best-effort: Apple's TestFlight screenshot CDN
# host is not publicly documented as a fixed pattern, so we allow the known
# Apple-owned suffixes and otherwise require https (see download_screenshot).
_APPLE_HOST_SUFFIXES = (".apple.com", ".mzstatic.com", ".icloud.com")


def _validate_app_id(asc_app_id: str) -> None:
    if not _APP_ID_RE.match(asc_app_id):
        raise ValueError("asc_app_id must contain digits only")


def _validate_limit(limit: int) -> None:
    if not 1 <= limit <= 200:
        raise ValueError("limit must be between 1 and 200 inclusive")


@mcp.tool()
async def list_screenshot_feedback(asc_app_id: str, limit: int = 50) -> dict:
    """List the most recent TestFlight screenshot feedback submissions for an app.

    Returns raw App Store Connect API JSON. asc_app_id is the app's numeric Apple ID.
    """
    _validate_app_id(asc_app_id)
    _validate_limit(limit)
    return await client.list_screenshot_feedback(asc_app_id, limit)


@mcp.tool()
async def list_crash_feedback(asc_app_id: str, limit: int = 50) -> dict:
    """List the most recent TestFlight crash feedback submissions for an app.

    Returns raw App Store Connect API JSON. asc_app_id is the app's numeric Apple ID.
    """
    _validate_app_id(asc_app_id)
    _validate_limit(limit)
    return await client.list_crash_feedback(asc_app_id, limit)


@mcp.tool()
async def get_crash_log(submission_id: str) -> dict:
    """Fetch the crash log for one crash feedback submission.

    Returns raw App Store Connect API JSON (.data.attributes.logText holds the log).
    """
    if not _SUBMISSION_ID_RE.match(submission_id):
        raise ValueError("submission_id may only contain letters, digits, and dashes")
    return await client.get_crash_log(submission_id)


@mcp.tool()
async def download_screenshot(url: str) -> Image:
    """Download a TestFlight feedback screenshot and return it as image content.

    Host validation is best-effort: Apple's screenshot CDN host is not publicly
    documented as a fixed pattern, so we require https and accept Apple-owned
    hostname suffixes.
    """
    parsed = httpx.URL(url)
    if parsed.scheme != "https":
        raise ValueError("url must be an https URL")
    host = parsed.host
    if not any(host == suffix.lstrip(".") or host.endswith(suffix) for suffix in _APPLE_HOST_SUFFIXES):
        raise ValueError("url host is not an Apple-controlled domain")

    async with httpx.AsyncClient(follow_redirects=False) as http:
        response = await http.get(url)
    if response.is_redirect:
        raise ValueError("url redirected; refusing to follow redirect off the allowed host")
    response.raise_for_status()

    content_type = response.headers.get("Content-Type", "image/png")
    image_format = content_type.split("/", 1)[-1].split(";", 1)[0].strip() or "png"
    return Image(data=response.content, format=image_format)


if __name__ == "__main__":
    mcp.run(transport="streamable-http")
