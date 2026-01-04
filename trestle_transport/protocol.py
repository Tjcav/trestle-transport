"""Protocol helpers for RockBridge Trestle transport frames."""

from __future__ import annotations

import time
import uuid
from typing import Any


def build_envelope(
    *,
    device_id: str,
    msg_type: str,
    body: dict[str, Any],
    msg_id: str | None = None,
) -> dict[str, Any]:
    """Build a canonical envelope for WS messages per ICD v4.1.

    Notes:
    - encoding defaults to "json" (omitted per spec)
    - compression defaults to "none" (omitted per spec)
    - Unknown optional fields MUST be ignored by recipient
    """
    return {
        "v": 1,
        "type": msg_type,
        "msg_id": msg_id or str(uuid.uuid4()),
        "device_id": device_id,
        "ts": int(time.time() * 1000),
        "body": body,
    }
