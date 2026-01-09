"""Protocol Buffer serialization for Trestle messages.

This module handles conversion between Python dictionaries and Protocol Buffer
messages for the Trestle coordinator-device protocol.

Architectural Boundary: This is ecosystem-agnostic transport code.
- NO Home Assistant-specific logic
- NO domain-specific fusion logic
- Pure message serialization/deserialization
"""

from __future__ import annotations

import logging
from typing import Any
from uuid import uuid4

from google.protobuf import struct_pb2, timestamp_pb2

from . import trestle_pb2

_LOGGER = logging.getLogger(__name__)


def dict_to_struct(data: dict[str, Any]) -> struct_pb2.Struct:
    """Convert Python dict to protobuf Struct.

    Args:
        data: Python dictionary

    Returns:
        Protobuf Struct
    """
    struct = struct_pb2.Struct()
    struct.update(data)
    return struct


def struct_to_dict(struct: struct_pb2.Struct) -> dict[str, Any]:
    """Convert protobuf Struct to Python dict.

    Args:
        struct: Protobuf Struct

    Returns:
        Python dictionary
    """
    return dict(struct)


def current_timestamp() -> timestamp_pb2.Timestamp:
    """Get current time as protobuf Timestamp.

    Returns:
        Current timestamp
    """
    ts = timestamp_pb2.Timestamp()
    ts.GetCurrentTime()
    return ts


def build_snapshot_message(
    profile_id: str,
    profile_version: str,
    fused_facts: dict[str, list[dict[str, Any]]],
    binding_states: list[dict[str, Any]],
    sequence_number: int,
) -> trestle_pb2.Message:
    """Build snapshot message.

    Args:
        profile_id: Active profile identifier
        profile_version: Profile version
        fused_facts: Map of domain_name -> list of domain facts
        binding_states: List of binding state updates
        sequence_number: Message sequence number

    Returns:
        Protobuf Message with snapshot payload
    """
    # Convert fused_facts to protobuf map
    fused_map = {}
    for domain_name, facts_list in fused_facts.items():
        # Wrap facts list in DomainData
        domain_data = trestle_pb2.DomainData(data=dict_to_struct({"facts": facts_list}))
        fused_map[domain_name] = domain_data

    # Build snapshot
    snapshot = trestle_pb2.Snapshot(
        profile_id=profile_id,
        profile_version=profile_version,
        fused_facts=fused_map,
        timestamp=current_timestamp(),
        sequence_number=sequence_number,
    )

    # TODO: Add binding states to snapshot
    # This requires adding bindings field to Snapshot message

    # Build message envelope
    message = trestle_pb2.Message(
        message_id=str(uuid4()),
        timestamp=current_timestamp(),
        snapshot=snapshot,
    )

    return message


def build_delta_message(
    profile_id: str,
    domain: str,
    changes: dict[str, Any],
    sequence_number: int,
) -> trestle_pb2.Message:
    """Build delta message.

    Args:
        profile_id: Active profile identifier
        domain: Domain that changed
        changes: Domain-specific changes
        sequence_number: Message sequence number

    Returns:
        Protobuf Message with delta payload
    """
    delta = trestle_pb2.Delta(
        profile_id=profile_id,
        domain=domain,
        changes=dict_to_struct(changes),
        timestamp=current_timestamp(),
        sequence_number=sequence_number,
    )

    message = trestle_pb2.Message(
        message_id=str(uuid4()),
        timestamp=current_timestamp(),
        delta=delta,
    )

    return message


def build_auth_request(
    token: str,
    device_id: str,
    firmware_version: str,
) -> trestle_pb2.Message:
    """Build authentication request message.

    Args:
        token: Shared secret token
        device_id: Device identifier
        firmware_version: Device firmware version

    Returns:
        Protobuf Message with auth_request payload
    """
    auth_req = trestle_pb2.AuthRequest(
        token=token,
        device_id=device_id,
        firmware_version=firmware_version,
    )

    message = trestle_pb2.Message(
        message_id=str(uuid4()),
        timestamp=current_timestamp(),
        auth_request=auth_req,
    )

    return message


def build_auth_response(
    success: bool,
    error_message: str | None,
    coordinator_version: str,
) -> trestle_pb2.Message:
    """Build authentication response message.

    Args:
        success: Whether authentication succeeded
        error_message: Error message if failed
        coordinator_version: Coordinator version string

    Returns:
        Protobuf Message with auth_response payload
    """
    auth_resp = trestle_pb2.AuthResponse(
        success=success,
        error_message=error_message or "",
        coordinator_version=coordinator_version,
    )

    message = trestle_pb2.Message(
        message_id=str(uuid4()),
        timestamp=current_timestamp(),
        auth_response=auth_resp,
    )

    return message


def serialize_message(message: trestle_pb2.Message) -> bytes:
    """Serialize protobuf message to binary.

    Args:
        message: Protobuf message

    Returns:
        Binary-serialized message
    """
    return message.SerializeToString()


def deserialize_message(data: bytes) -> trestle_pb2.Message:
    """Deserialize binary data to protobuf message.

    Args:
        data: Binary message data

    Returns:
        Parsed protobuf message

    Raises:
        DecodeError: If data is invalid
    """
    message = trestle_pb2.Message()
    message.ParseFromString(data)
    return message


def get_message_type(message: trestle_pb2.Message) -> str | None:
    """Get the type of message payload.

    Args:
        message: Protobuf message

    Returns:
        Payload type name or None
    """
    which = message.WhichOneof("payload")
    return which
