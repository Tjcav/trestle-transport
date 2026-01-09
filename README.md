# trestle-coordinator-core

Shared coordinator foundation for Trestle implementations. Provides protocol transport, session management, and message builders.

This package provides:
- **TrestleSession** - High-level session manager for device communication
- **TrestleWsClient** - WebSocket client for Trestle protocol
- **TrestleHttpClient** - HTTP client for pairing, unpair, screenshots
- **Protocol builders** - Message envelope and body builders

## Install (GitHub)

```bash
pip install git+ssh://git@github.com/tjcav/trestle-transport.git@main
```

## Usage

### TrestleSession (Recommended)

Use `TrestleSession` for high-level device communication with automatic connection management, batching, and protocol handling:

```python
from trestle_coordinator_core import TrestleSession

# Create session
session = TrestleSession(
    host="192.168.1.100",
    port=80,
    device_id="device-123",
    secret="pairing-secret",
    protocol_versions=[1],
    on_input_event=handle_input,
    on_state_request=handle_state_request,
)

# Connect
await session.connect()

# Send layout
await session.send_layout(layout_package)

# Send state updates (batched automatically)
session.schedule_state_update("binding_1", "on")
session.schedule_state_update("binding_2", 75.5)

# Close
await session.close()
```

### Low-level Protocol Builders

For custom implementations or testing:

```python
from trestle_coordinator_core import (
    SUPPORTED_PROTOCOL_VERSIONS,
    TrestleWsClient,
    TrestleHttpClient,
    build_envelope,
    build_time_body,
)
```
