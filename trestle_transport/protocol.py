"""Protocol helpers for Rocky Panel transport frames."""

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
    encoding: str = "json",
    compression: str = "none",
) -> dict[str, Any]:
    """Build a canonical envelope for WS messages."""
    return {
        "v": 1,
        "type": msg_type,
        "msg_id": msg_id or str(uuid.uuid4()),
        "device_id": device_id,
        "ts": int(time.time() * 1000),
        "encoding": encoding,
        "compression": compression,
        "body": body,
    }
