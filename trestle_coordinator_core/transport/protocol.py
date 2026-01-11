"""Protocol helpers for RockBridge Trestle transport frames.

Owned by the Trestle Coordinator Core team.

This module provides JSON message building for legacy protocol support.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable, Sequence
from datetime import datetime
from typing import Any, TypeGuard


def _is_protocol_iterable(value: Any) -> TypeGuard[Iterable[Any]]:
    """Return True when value is a non-string iterable."""
    return not isinstance(value, (str, bytes)) and isinstance(value, Iterable)


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


def _normalize_protocol_versions(versions: Any) -> tuple[int, ...]:
    """Normalize protocol version iterables into canonical integer tuples.

    Args:
        versions: Value to validate and normalize (should be iterable of ints)

    Returns:
        Tuple of validated integer protocol versions

    Raises:
        ValueError: If versions is not iterable or contains non-integers
    """
    # Validate it's iterable but not string/bytes
    if isinstance(versions, (str, bytes)):
        raise ValueError("Protocol versions must not be string or bytes")
    if not _is_protocol_iterable(versions):
        raise ValueError("Protocol versions must be an iterable")

    # Convert to list for validation
    versions_list: list[Any] = list(versions)
    if not versions_list:
        raise ValueError("At least one protocol version is required")

    # Validate each element is an integer (not bool which is subclass of int)
    normalized: list[int] = []
    for idx, version in enumerate(versions_list):
        if isinstance(version, bool):
            raise ValueError(f"Protocol version at index {idx} is bool, must be int")
        if not isinstance(version, int):
            raise ValueError(
                f"Protocol version at index {idx} must be integer, got {type(version).__name__}"
            )
        normalized.append(version)

    return tuple(normalized)


def parse_auth_ok(message: dict[str, Any]) -> tuple[int, ...]:
    """Extract supported coordinator protocol versions from auth_ok payload.

    Devices expect the coordinator to advertise supported protocol versions
    during authentication so they can negotiate prior to capability exchange.

    Raises ValueError if coordinator_protocol_versions is missing or invalid.
    """
    versions_raw = message.get("coordinator_protocol_versions")
    if versions_raw is None:
        raise ValueError("coordinator_protocol_versions field is required in auth_ok")

    # Let _normalize_protocol_versions do full validation
    return _normalize_protocol_versions(versions_raw)


def build_auth_ok(
    *,
    device_id: str,
    coordinator_versions: Sequence[int],
    msg_id: str | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Construct an auth_ok frame declaring coordinator protocol versions."""
    normalized = _normalize_protocol_versions(coordinator_versions)
    return build_envelope(
        device_id=device_id,
        msg_type="auth_ok",
        msg_id=msg_id,
        timestamp_ms=timestamp_ms,
        body={"coordinator_protocol_versions": list(normalized)},
    )


def build_auth_confirmed(
    *,
    device_id: str,
    msg_id: str | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Construct an auth_confirmed frame (ICD 5.4).

    Coordinator sends this after successfully validating device's auth_ok.
    Device must receive this before transitioning to authenticated state.
    """
    return build_envelope(
        device_id=device_id,
        msg_type="auth_confirmed",
        msg_id=msg_id,
        timestamp_ms=timestamp_ms,
        body={},
    )


def build_auth_invalid(
    *,
    device_id: str,
    message: str,
    msg_id: str | None = None,
    timestamp_ms: int | None = None,
) -> dict[str, Any]:
    """Construct an auth_invalid frame notifying the device of failure."""
    if not message:
        raise ValueError("message is required for auth_invalid frames")
    return build_envelope(
        device_id=device_id,
        msg_type="auth_invalid",
        msg_id=msg_id,
        timestamp_ms=timestamp_ms,
        body={"message": message},
    )
