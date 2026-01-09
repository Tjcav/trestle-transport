# Architecture Overview

## Design Philosophy

trestle-coordinator-core is designed as a **transport layer library** that handles low-level communication with Trestle devices. It provides:

1. **Protocol abstraction** - Hide WebSocket/HTTP details
2. **Connection management** - Handle reconnection, batching, timeouts
3. **Type safety** - Full type hints for better developer experience
4. **Testability** - Easy to mock and test

## Layer Architecture

```
┌─────────────────────────────────────┐
│   Integration Layer (trestle-ha)   │  <- Home Assistant integration
├─────────────────────────────────────┤
│      TrestleSession (High-level)    │  <- Session management, batching
├─────────────────────────────────────┤
│  TrestleWsClient / TrestleHttpClient│  <- Protocol transport
├─────────────────────────────────────┤
│      Protocol Builders/Parsers      │  <- Message construction
├─────────────────────────────────────┤
│     WebSocket / HTTP (aiohttp)      │  <- Network layer
└─────────────────────────────────────┘
```

## Core Components

### TrestleSession

**Purpose:** High-level device session manager

**Responsibilities:**
- Connection lifecycle (connect, reconnect, close)
- Handshake orchestration
- Automatic state update batching
- Event routing (input events, state requests)
- Error recovery

**Key Features:**
- Transparent reconnection
- Batched updates (configurable delay)
- Callback-based event handling
- Protocol version negotiation

### TrestleWsClient

**Purpose:** WebSocket protocol wrapper

**Responsibilities:**
- WebSocket connection management
- Message serialization (JSON/binary)
- Message iteration (async iterator pattern)
- Connection health monitoring

**Key Features:**
- Supports both `websockets` and `aiohttp` backends
- Type-safe message handling
- Graceful shutdown

### TrestleHttpClient

**Purpose:** HTTP operations (pairing, screenshots)

**Responsibilities:**
- Pairing/unpairing device coordination
- Screenshot retrieval
- HTTP error handling

**Key Features:**
- Async HTTP requests
- Structured error responses
- Timeout management

### Protocol Builders

**Purpose:** Construct protocol messages

**Responsibilities:**
- Build valid Trestle envelopes
- Create message bodies (time, auth, layout, state)
- Parse incoming messages
- Version compatibility

**Key Features:**
- Protocol version support
- Consistent message structure
- Type-safe builders

## Data Flow

### Connection Establishment

```
TrestleSession.connect()
    ↓
TrestleWsClient.connect()
    ↓
Send auth_ok message (with secret)
    ↓
Receive auth_confirmed
    ↓
Connection established
```

### State Update Flow

```
Integration calls schedule_state_update()
    ↓
Batch updates for batch_delay seconds
    ↓
Send batched state message
    ↓
Device acknowledges
```

### Input Event Flow

```
Device sends input event
    ↓
TrestleWsClient receives message
    ↓
TrestleSession routes to on_input_event callback
    ↓
Integration handles event
```

## Error Handling Strategy

### Exception Hierarchy

```
TrestleClientError (base)
├── TrestleConnectionError (network issues)
├── TrestleHandshakeError (auth/protocol errors)
├── TrestleResponseError (device errors)
└── TrestleTimeout (operation timeouts)
```

### Error Recovery

- **Connection errors**: Allow retry with exponential backoff
- **Handshake errors**: Fatal - require new connection
- **Response errors**: Log and continue operation
- **Timeouts**: Configurable per operation

## Async Design

### Event Loop Integration

All I/O operations are async to integrate with asyncio event loops:

```python
# Non-blocking connection
await session.connect()

# Non-blocking message sending
await session.send_layout(layout)

# Async iteration over messages
async for message in client.receive_messages():
    handle_message(message)
```

### Concurrency Patterns

- **Batching**: Use `asyncio.create_task()` for delayed sends
- **Timeouts**: `asyncio.wait_for()` on all network operations
- **Cancellation**: Proper cleanup on task cancellation

## Testing Strategy

### Unit Tests

- Mock external dependencies (websockets, aiohttp)
- Test individual components in isolation
- Use pytest fixtures for common setups

### Integration Tests

- Test full connection flow
- Verify protocol compliance
- Test error scenarios

### Coverage Goals

- Minimum 95% code coverage
- 100% coverage for critical paths
- Exclude generated code (protobuf stubs)

## Dependencies

### Required

- `websockets>=14.0` - WebSocket client

### Optional

- `protobuf` - For protobuf message support
- `aiohttp` - Alternative WebSocket backend

### Development

- `pytest` - Testing framework
- `pytest-asyncio` - Async test support
- `pytest-cov` - Coverage reporting
- `ruff` - Linting and formatting
- `mypy` - Type checking
- `bandit` - Security scanning

## Extension Points

### Custom Transports

Implement custom WebSocket clients by conforming to the `TrestleWsClient` interface:

```python
class MyCustomClient:
    async def connect(self) -> None: ...
    async def send_json(self, data: dict) -> None: ...
    def receive_messages(self) -> AsyncIterator[TrestleWsMessage]: ...
```

### Protocol Extensions

Extend protocol builders for custom message types:

```python
def build_custom_body(data: dict) -> dict[str, Any]:
    return {
        "type": "custom",
        "payload": data,
    }
```

### Event Handlers

Implement custom event handlers:

```python
async def my_input_handler(event: dict) -> None:
    # Custom logic for input events
    pass

session = TrestleSession(
    ...,
    on_input_event=my_input_handler,
)
```

## Performance Considerations

### Batching

State updates are batched to reduce message overhead:
- Default: 100ms delay
- Configurable via `batch_delay` parameter
- Trade-off: Latency vs. efficiency

### Memory

- Message buffers are bounded
- Old messages are discarded on overflow
- Connection state is lightweight

### CPU

- JSON serialization is the main CPU cost
- Consider protobuf for high-frequency updates
- Async operations minimize blocking

## Security

### Secrets Management

- Pairing secrets stored in memory only
- Never logged or exposed in errors
- Transmitted over WebSocket (consider TLS in production)

### Input Validation

- All incoming messages validated
- Unknown message types ignored
- Malformed messages logged and discarded

### Dependency Security

- Regular dependency updates
- Bandit security scanning in CI
- No known CVEs in dependencies
