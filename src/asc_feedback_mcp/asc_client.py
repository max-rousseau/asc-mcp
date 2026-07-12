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
    """A non-2xx response from the App Store Connect API.

    Attributes:
        status_code: The HTTP status code returned by the API.
        body: The raw response body text.
        url: The request URL that failed.
    """

    def __init__(self, status_code: int, body: str, url: str) -> None:
        """Build the error from the failing response's status, body, and URL.

        Args:
            status_code: The HTTP status code returned by the API.
            body: The raw response body text.
            url: The request URL that failed.
        """
        super().__init__(f"App Store Connect API request failed ({status_code}) for {url}: {body}")
        self.status_code = status_code
        self.body = body
        self.url = url


class AscClient:
    """App Store Connect client that mints/caches an ES256 bearer token.

    Attributes:
        _token: The cached JWT, or ``None`` if none has been minted yet.
        _token_exp: Unix timestamp when the cached token expires.

    Example:
        >>> result = await client.list_crash_feedback("123456789", 50)
    """

    def __init__(self) -> None:
        """Initialize the client with no cached token."""
        self._token: str | None = None
        self._token_exp: float = 0.0

    def _bearer_token(self) -> str:
        """Return a cached or freshly minted ES256 JWT bearer token.

        Re-mints the token when the cached one is unset or within
        ``_RENEW_SKEW`` seconds of expiry.

        Returns:
            The encoded JWT string, ready for use as a Bearer token.
        """
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
        """Issue an authenticated GET request against the App Store Connect API.

        Args:
            path: The API path (including query string), relative to
                ``API_BASE``.

        Returns:
            The parsed JSON response body.

        Raises:
            AscApiError: If the response status is not a 2xx success.
        """
        url = f"{API_BASE}{path}"
        headers = {"Authorization": f"Bearer {self._bearer_token()}"}
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=headers)
        if not response.is_success:
            raise AscApiError(response.status_code, response.text, url)
        return response.json()

    async def list_screenshot_feedback(self, asc_app_id: str, limit: int) -> dict:
        """List the most recent TestFlight screenshot feedback for an app.

        Args:
            asc_app_id: The app's numeric Apple ID.
            limit: Maximum number of submissions to return.

        Returns:
            The raw App Store Connect API JSON response.

        Raises:
            AscApiError: If the request fails with a non-2xx response.
        """
        path = (
            f"/v1/apps/{asc_app_id}/betaFeedbackScreenshotSubmissions"
            f"?sort=-createdDate&limit={limit}&include=build"
            f"&fields[betaFeedbackScreenshotSubmissions]={_SCREENSHOT_FIELDS}"
        )
        return await self._get(path)

    async def list_crash_feedback(self, asc_app_id: str, limit: int) -> dict:
        """List the most recent TestFlight crash feedback for an app.

        Args:
            asc_app_id: The app's numeric Apple ID.
            limit: Maximum number of submissions to return.

        Returns:
            The raw App Store Connect API JSON response.

        Raises:
            AscApiError: If the request fails with a non-2xx response.
        """
        path = (
            f"/v1/apps/{asc_app_id}/betaFeedbackCrashSubmissions"
            f"?sort=-createdDate&limit={limit}&include=build"
        )
        return await self._get(path)

    async def get_crash_log(self, submission_id: str) -> dict:
        """Fetch the crash log for a single crash feedback submission.

        Args:
            submission_id: The crash feedback submission id.

        Returns:
            The raw App Store Connect API JSON response
            (``.data.attributes.logText`` holds the log text).

        Raises:
            AscApiError: If the request fails with a non-2xx response.
        """
        return await self._get(f"/v1/betaFeedbackCrashSubmissions/{submission_id}/crashLog")


client = AscClient()
