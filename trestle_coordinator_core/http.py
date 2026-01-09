"""HTTP client for RockBridge Trestle device endpoints."""

from __future__ import annotations

from typing import Final

import aiohttp

from .errors import (
    TrestleConnectionError,
    TrestleResponseError,
    TrestleTimeout,
)

# Sentinel value to explicitly request no authentication
_NO_AUTH: Final = object()


class TrestleHttpClient:
    """HTTP client wrapper for RockBridge Trestle device endpoints."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        host: str,
        port: int,
        *,
        secret: str | None = None,
    ) -> None:
        self._session = session
        self._host = host
        self._port = port
        self._secret = secret

    def _url(self, path: str) -> str:
        return f"http://{self._host}:{self._port}{path}"

    def _auth_headers(self, secret: str | None | object = None) -> dict[str, str]:
        # Check for explicit no-auth sentinel
        if secret is _NO_AUTH:
            return {}
        token = secret if secret is not None else self._secret
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    async def fetch_device_id(
        self,
        *,
        retry_without_auth: bool = True,
        _secret_override: str | None | object = None,
    ) -> str | None:
        """Fetch device-provided unique ID from /api/info endpoint.

        Per ICD Section 3.1, after pairing the endpoint requires Bearer token
        authentication. Before pairing, it must allow unauthenticated access.

        Per ICD Section 3.2, when encountering 401 with stored secret (orphan
        panel scenario), coordinator MUST attempt unpair to recover.

        Args:
            retry_without_auth: If True and 401 received, retry without auth
                after unpair attempt.
            _secret_override: Internal parameter for retry logic.

        Returns:
            Device ID string, or None if request failed.
        """
        url = self._url("/api/info")
        # Use override if provided, otherwise use instance secret
        if _secret_override is not None:
            headers = self._auth_headers(_secret_override)
        else:
            headers = self._auth_headers()

        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                # ICD 3.1: After pairing, device MUST return 401 if token missing/invalid
                if resp.status == 401 and self._secret and retry_without_auth:
                    # Device rejected auth - orphan panel scenario (ICD 3.2)
                    # Unpair device to force back to unpaired state
                    await self.unpair_device()

                    # Retry without auth
                    return await self.fetch_device_id(
                        retry_without_auth=False, _secret_override=_NO_AUTH
                    )

                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("id") or data.get("unique_id") or data.get("device_id")
        except TimeoutError as err:
            raise TrestleTimeout("Device info request timed out") from err
        except aiohttp.ClientError as err:
            raise TrestleConnectionError("Failed to fetch device info") from err

    async def send_pairing_secret(self, secret: str) -> None:
        """Send pairing secret to /pair endpoint."""
        url = self._url("/pair")
        try:
            async with self._session.post(
                url,
                json={"secret": secret},
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                if resp.status != 200:
                    raise TrestleResponseError(
                        resp.status, "Pairing failed with non-200 response"
                    )
        except TimeoutError as err:
            raise TrestleTimeout("Pairing request timed out") from err
        except aiohttp.ClientError as err:
            raise TrestleConnectionError("Pairing request failed") from err

    async def unpair_device(self) -> None:
        """Unpair device via unauthenticated /api/unpair endpoint (ICD 3.2).

        Per ICD Section 3.2, this endpoint solves orphan panel scenarios where
        the device has a stored secret but coordinator has lost it.

        The endpoint MUST:
        - Accept unauthenticated POST requests
        - Clear stored pairing secret from device NVS
        - Return HTTP 200 with body "OK" on success
        - Be idempotent (return 200 if already unpaired)

        Raises:
            TrestleResponseError: If device returns non-200 status
            TrestleTimeout: If request times out
            TrestleConnectionError: If network request fails
        """
        url = self._url("/api/unpair")
        try:
            async with self._session.post(
                url,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                # ICD 3.2.1: Device MUST return 200 with body "OK"
                if resp.status != 200:
                    raise TrestleResponseError(
                        resp.status,
                        "Unpair failed - device must return 200 OK per ICD 3.2",
                    )
        except TimeoutError as err:
            raise TrestleTimeout("Unpair request timed out") from err
        except aiohttp.ClientError as err:
            raise TrestleConnectionError("Unpair request failed") from err

    async def fetch_screenshot(self, secret: str | None) -> tuple[bytes, str] | None:
        """Fetch device screenshot from /api/screenshot endpoint."""
        url = self._url("/api/screenshot")
        headers = self._auth_headers(secret)
        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return None
                image_data = await resp.read()
                content_type = resp.headers.get("Content-Type", "image/png")
                return image_data, content_type
        except TimeoutError as err:
            raise TrestleTimeout("Screenshot request timed out") from err
        except aiohttp.ClientError as err:
            raise TrestleConnectionError("Screenshot request failed") from err
