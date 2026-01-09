# API Reference

## TrestleSession

High-level session manager for Trestle device communication.

### Constructor

```python
TrestleSession(
    host: str,
    port: int,
    device_id: str,
    secret: str,
    protocol_versions: list[int] = [1],
    on_input_event: Callable[[dict], Awaitable[None]] | None = None,
    on_state_request: Callable[[str], Awaitable[Any]] | None = None,
    on_disconnected: Callable[[], None] | None = None,
    batch_delay: float = 0.1,
)
```

**Parameters:**
- `host`: Device IP address or hostname
- `port`: WebSocket port (typically 80)
- `device_id`: Unique device identifier
- `secret`: Pairing secret from device
- `protocol_versions`: Supported protocol versions (default: [1])
- `on_input_event`: Callback for input events from device
- `on_state_request`: Callback when device requests state
- `on_disconnected`: Callback when connection is lost
- `batch_delay`: Delay before sending batched updates (seconds)

### Methods

#### connect()

```python
async def connect() -> None
```

Connect to the device and perform handshake.

**Raises:**
- `TrestleConnectionError`: Connection failed
- `TrestleHandshakeError`: Handshake failed
- `TrestleTimeout`: Connection timeout

#### close()

```python
async def close() -> None
```

Close the connection gracefully.

#### send_layout()

```python
async def send_layout(layout: dict[str, Any]) -> bool
```

Send a layout package to the device.

**Parameters:**
- `layout`: Layout package dictionary

**Returns:** True if sent successfully

#### schedule_state_update()

```python
def schedule_state_update(binding_id: str, value: Any) -> None
```

Schedule a state update (batched automatically).

**Parameters:**
- `binding_id`: Binding identifier
- `value`: New value for the binding

#### send_protobuf_message()

```python
async def send_protobuf_message(message: Message) -> bool
```

Send a protobuf message (requires protobuf dependency).

**Parameters:**
- `message`: Protobuf message instance

**Returns:** True if sent successfully

**Note:** Requires `protobuf` package to be installed.

### Properties

#### is_connected

```python
@property
def is_connected() -> bool
```

Check if currently connected to device.

## TrestleWsClient

Low-level WebSocket client for Trestle protocol.

### Constructor

```python
TrestleWsClient(
    url: str,
    close_timeout: float = 10.0,
)
```

**Parameters:**
- `url`: WebSocket URL (e.g., `ws://192.168.1.100:80/ws`)
- `close_timeout`: Timeout for close operations

### Methods

#### connect()

```python
async def connect() -> None
```

Establish WebSocket connection.

**Raises:**
- `TrestleConnectionError`: Connection failed

#### close()

```python
async def close() -> None
```

Close WebSocket connection.

#### send_json()

```python
async def send_json(data: dict[str, Any]) -> None
```

Send JSON message.

**Parameters:**
- `data`: Dictionary to send as JSON

#### send_bytes()

```python
async def send_bytes(data: bytes) -> None
```

Send binary message.

**Parameters:**
- `data`: Bytes to send

#### receive_messages()

```python
def receive_messages() -> AsyncIterator[TrestleWsMessage]
```

Iterate over incoming messages.

**Yields:** `TrestleWsMessage` instances

## TrestleHttpClient

HTTP client for pairing, unpair, and screenshots.

### Constructor

```python
TrestleHttpClient(
    base_url: str,
    timeout: float = 30.0,
)
```

**Parameters:**
- `base_url`: Base URL (e.g., `http://192.168.1.100`)
- `timeout`: Request timeout in seconds

### Methods

#### pair()

```python
async def pair(mac_address: str) -> dict[str, Any]
```

Initiate pairing with device.

**Parameters:**
- `mac_address`: Coordinator MAC address

**Returns:** Pairing response with secret

**Raises:**
- `TrestleResponseError`: Pairing failed

#### unpair()

```python
async def unpair(mac_address: str, secret: str) -> None
```

Unpair from device.

**Parameters:**
- `mac_address`: Coordinator MAC address
- `secret`: Pairing secret

**Raises:**
- `TrestleResponseError`: Unpair failed

#### get_screenshot()

```python
async def get_screenshot() -> bytes
```

Get PNG screenshot from device.

**Returns:** PNG image bytes

**Raises:**
- `TrestleResponseError`: Screenshot failed

## Protocol Builders

Low-level protocol message builders.

### build_envelope()

```python
def build_envelope(
    sender_id: str,
    body: dict[str, Any],
    protocol_version: int = 1,
) -> dict[str, Any]
```

Build a Trestle protocol envelope.

**Parameters:**
- `sender_id`: Sender identifier
- `body`: Message body
- `protocol_version`: Protocol version

**Returns:** Complete envelope dictionary

### build_time_body()

```python
def build_time_body() -> dict[str, Any]
```

Build a time synchronization message body.

**Returns:** Time message body with current UTC time

### build_auth_ok()

```python
def build_auth_ok(secret: str) -> dict[str, Any]
```

Build authentication OK message.

**Parameters:**
- `secret`: Pairing secret

**Returns:** Auth OK message body

## Exceptions

All exceptions inherit from `TrestleClientError`.

### TrestleConnectionError

Raised when connection to device fails.

### TrestleHandshakeError

Raised when handshake process fails.

### TrestleResponseError

Raised when device responds with an error.

### TrestleTimeout

Raised when an operation times out.

## Constants

### SUPPORTED_PROTOCOL_VERSIONS

```python
SUPPORTED_PROTOCOL_VERSIONS: tuple[int, ...] = (1,)
```

Tuple of supported protocol versions.
