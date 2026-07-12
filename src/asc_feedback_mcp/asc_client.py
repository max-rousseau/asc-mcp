"""Async App Store Connect API client with a cached ES256 JWT.

Mints an ES256 JWT from the .p8 EC private key (PyJWT + cryptography) and caches
it in memory, re-minting only when it is within ~60s of expiry. All calls go
through an httpx.AsyncClient against the App Store Connect API.
"""

from __future__ import annotations

import time

import httpx
import jwt

from .config import config

API_BASE = "https://api.appstoreconnect.apple.com"
_TOKEN_LIFETIME = 1200  # ASC max token lifetime is 20 minutes.
_RENEW_SKEW = 60  # Re-mint when within this many seconds of expiry.

_SCREENSHOT_FIELDS = (
    "createdDate,comment,email,deviceModel,osVersion,"
    "appUptimeInMilliseconds,batteryPercentage,screenshots,build"
)


class AscApiError(RuntimeError):
    """A non-2xx response from the App Store Connect API."""

    def __init__(self, status_code: int, body: str, url: str) -> None:
        super().__init__(f"App Store Connect API request failed ({status_code}) for {url}: {body}")
        self.status_code = status_code
        self.body = body
        self.url = url


class AscClient:
    """App Store Connect client that mints/caches an ES256 bearer token."""

    def __init__(self) -> None:
        self._token: str | None = None
        self._token_exp: float = 0.0

    def _bearer_token(self) -> str:
        now = time.time()
        if self._token is not None and now < self._token_exp - _RENEW_SKEW:
            return self._token

        iat = int(now)
        exp = iat + _TOKEN_LIFETIME
        token = jwt.encode(
            {
                "iss": config.issuer_id,
                "iat": iat,
                "exp": exp,
                "aud": "appstoreconnect-v1",
            },
            config.private_key,
            algorithm="ES256",
            headers={"alg": "ES256", "kid": config.key_id, "typ": "JWT"},
        )
        self._token = token
        self._token_exp = exp
        return token

    async def _get(self, path: str) -> dict:
        url = f"{API_BASE}{path}"
        headers = {"Authorization": f"Bearer {self._bearer_token()}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
        if not response.is_success:
            raise AscApiError(response.status_code, response.text, url)
        return response.json()

    async def list_screenshot_feedback(self, asc_app_id: str, limit: int) -> dict:
        path = (
            f"/v1/apps/{asc_app_id}/betaFeedbackScreenshotSubmissions"
            f"?sort=-createdDate&limit={limit}&include=build"
            f"&fields[betaFeedbackScreenshotSubmissions]={_SCREENSHOT_FIELDS}"
        )
        return await self._get(path)

    async def list_crash_feedback(self, asc_app_id: str, limit: int) -> dict:
        path = (
            f"/v1/apps/{asc_app_id}/betaFeedbackCrashSubmissions"
            f"?sort=-createdDate&limit={limit}&include=build"
        )
        return await self._get(path)

    async def get_crash_log(self, submission_id: str) -> dict:
        return await self._get(f"/v1/betaFeedbackCrashSubmissions/{submission_id}/crashLog")


client = AscClient()
