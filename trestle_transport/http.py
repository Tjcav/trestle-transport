"""HTTP client for Rocky Panel device endpoints."""

from __future__ import annotations

import aiohttp

from .errors import (
    RockyPanelConnectionError,
    RockyPanelResponseError,
    RockyPanelTimeout,
)


class RockyPanelHttpClient:
    """HTTP client wrapper for Rocky Panel device endpoints."""

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

    def _auth_headers(self, secret: str | None = None) -> dict[str, str]:
        token = secret or self._secret
        if not token:
            return {}
        return {"Authorization": f"Bearer {token}"}

    async def fetch_device_id(self) -> str | None:
        """Fetch device-provided unique ID from /api/info endpoint."""
        url = self._url("/api/info")
        headers = self._auth_headers()
        try:
            async with self._session.get(
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                return data.get("id") or data.get("unique_id") or data.get("device_id")
        except TimeoutError as err:
            raise RockyPanelTimeout("Device info request timed out") from err
        except aiohttp.ClientError as err:
            raise RockyPanelConnectionError("Failed to fetch device info") from err

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
                    raise RockyPanelResponseError(
                        resp.status, "Pairing failed with non-200 response"
                    )
        except TimeoutError as err:
            raise RockyPanelTimeout("Pairing request timed out") from err
        except aiohttp.ClientError as err:
            raise RockyPanelConnectionError("Pairing request failed") from err

    async def unpair(self, secret: str) -> tuple[int, str]:
        """Unpair the device by calling /unpair endpoint."""
        url = self._url("/unpair")
        try:
            async with self._session.post(
                url,
                json={"secret": secret},
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                body = await resp.text()
                return resp.status, body
        except TimeoutError as err:
            raise RockyPanelTimeout("Unpair request timed out") from err
        except aiohttp.ClientError as err:
            raise RockyPanelConnectionError("Unpair request failed") from err

    async def reset_device(self, *, raise_on_error: bool = True) -> int:
        """Trigger device reset via /reset endpoint."""
        url = self._url("/reset")
        try:
            async with self._session.post(
                url,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                if raise_on_error and resp.status != 200:
                    raise RockyPanelResponseError(
                        resp.status, "Reset request failed with non-200 response"
                    )
                return resp.status
        except TimeoutError as err:
            raise RockyPanelTimeout("Reset request timed out") from err
        except aiohttp.ClientError as err:
            raise RockyPanelConnectionError("Reset request failed") from err

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
            raise RockyPanelTimeout("Screenshot request timed out") from err
        except aiohttp.ClientError as err:
            raise RockyPanelConnectionError("Screenshot request failed") from err
