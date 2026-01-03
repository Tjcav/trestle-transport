# trestle-transport

Trestle WebSocket/HTTP transport adapter and JSON framing helpers.

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
from trestle_transport import RockyPanelHttpClient, RockyPanelWsClient
```
