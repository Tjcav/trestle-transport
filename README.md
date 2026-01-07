# trestle-coordinator-core

Shared coordinator foundation for Trestle implementations. Provides
transport adapters, canonical envelope builders, and protocol negotiation
helpers.

This package provides:
- WebSocket connection helpers for Trestle devices
- HTTP helpers for pairing, screenshots, and device ops
- JSON frame envelope utilities

## Install (GitHub)

```bash
pip install git+ssh://git@github.com/tjcav/trestle-transport.git@main
```

## Usage

```python
from trestle_coordinator_core import (
	SUPPORTED_PROTOCOL_VERSIONS,
	TrestleHttpClient,
	TrestleWsClient,
	build_envelope,
	build_time_body,
)
```
