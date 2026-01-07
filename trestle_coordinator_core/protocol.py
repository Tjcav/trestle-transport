"""Protocol helpers for RockBridge Trestle transport frames.

Owned by the Trestle Coordinator Core team.
"""

from __future__ import annotations

from datetime import datetime
import time
import uuid
from typing import Any, Iterable


def build_envelope(
    *,
    device_id: str,
    msg_type: str,
    body: dict[str, Any],
    msg_id: str | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Build a canonical envelope for coordinator messages.

    Args:
        device_id: Canonical device UUID.
        msg_type: Canonical message type (e.g., "time", "snapshot").
        body: JSON-serializable body adhering to the ICD schema.
        msg_id: Optional caller-supplied identifier. Generated when omitted.
        timestamp_ms: Optional epoch milliseconds override.

    Returns:
        Canonical envelope dict compliant with the specification.
    """
    return {
        "v": 1,
        "type": msg_type,
        "msg_id": msg_id or str(uuid.uuid4()),
        "device_id": device_id,
        "ts": timestamp_ms if timestamp_ms is not None else int(time.time() * 1000),
        "body": body,
    }


def build_time_body(
    now: datetime, *, timezone_name: str | None = None
) -> dict[str, Any]:
    """Create a time-sync payload honoring ICD epoch requirements.

    Args:
        now: Timezone-aware datetime representing coordinator time.
        timezone_name: Optional Olson/IANA timezone identifier to include.

    Returns:
        Body dict containing epoch seconds, UTC offset seconds, and optional
        timezone identifier.
    """

    epoch = int(now.timestamp())
    offset = now.utcoffset()
    body: dict[str, Any] = {"epoch": epoch, "utc_offset": 0}

    if offset is not None:
        body["utc_offset"] = int(offset.total_seconds())

    if timezone_name:
        body["timezone"] = timezone_name

    return body


def _normalize_protocol_versions(versions: Iterable[Any]) -> tuple[int, ...]:
    """Normalize protocol version iterables into canonical integer tuples."""

    normalized: list[int] = []
    for version in versions:
        if isinstance(version, bool) or not isinstance(version, int):
            raise ValueError("Protocol versions must be integers")
        normalized.append(version)
    if not normalized:
        raise ValueError("At least one protocol version is required")
    return tuple(normalized)


def parse_auth_ok(message: dict[str, Any]) -> tuple[int, ...]:
    """Extract supported coordinator protocol versions from auth_ok payload.

    Devices expect the coordinator to advertise supported protocol versions
    during authentication so they can negotiate prior to capability exchange.
    """

    versions = message.get("coordinator_protocol_versions")
    if versions is None:
        return ()
    if not isinstance(versions, Iterable) or isinstance(versions, (str, bytes)):
        raise ValueError("coordinator_protocol_versions must be an iterable")
    return _normalize_protocol_versions(versions)
