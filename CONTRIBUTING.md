# Contributing to trestle-coordinator-core

Thank you for considering contributing to trestle-coordinator-core!

## Development Setup

1. **Clone the repository:**

   ```bash
   git clone https://github.com/tjcav/trestle-transport.git
   cd trestle-transport
   ```

2. **Create a virtual environment:**

   ```bash
   python -m venv .venv
   source .venv/bin/activate  # On Windows: .venv\Scripts\activate
   ```

3. **Install development dependencies:**
   ```bash
   pip install -e ".[dev]"
   pip install pre-commit
   pre-commit install
   ```

## Code Quality Standards

This project maintains high code quality standards:

- **Type Hints**: All functions must have type hints
- **Testing**: Minimum 95% code coverage required
- **Linting**: Ruff for code quality (see `ruff.toml`)
- **Type Checking**: Mypy/Pyright for static analysis
- **Security**: Bandit for security scanning
- **Formatting**: Ruff formatter (auto-applied)

### Central tooling standard

This repo follows the centralized tooling standard. The authoritative pin is in [.trestle/standards.version](.trestle/standards.version).
For orientation only, see https://github.com/tjcav/trestle-spec/tree/main/tooling.

## Development Workflow

1. **Create a feature branch:**

   ```bash
   git checkout -b feature/your-feature-name
   ```

2. **Make your changes**

3. **Run tests:**

   ```bash
   pytest tests/ -v --cov=trestle_coordinator_core
   ```

4. **Run pre-commit checks:**

   ```bash
   pre-commit run --all-files
   ```

5. **Commit your changes:**

   ```bash
   git add .
   git commit -m "feat: add your feature description"
   ```

6. **Push and create a pull request:**
   ```bash
   git push origin feature/your-feature-name
   ```

## Commit Message Convention

We follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` - New feature
- `fix:` - Bug fix
- `docs:` - Documentation changes
- `test:` - Test additions/changes
- `refactor:` - Code refactoring
- `perf:` - Performance improvements
- `chore:` - Build/tooling changes

## Code Guidelines

### Error Handling

All exceptions should inherit from `TrestleClientError`:

```python
class TrestleMyError(TrestleClientError):
    """Descriptive error message."""
```

Document which exceptions each function can raise:

```python
async def my_function() -> None:
    """Do something.

    Raises:
        TrestleConnectionError: When connection fails
        TrestleTimeout: When operation times out
    """
```

### Logging

Use lazy logging to avoid string formatting overhead:

```python
# ✅ Good - lazy evaluation
_LOGGER.debug("Processing %d items for %s", count, device_id)

# ❌ Bad - eager evaluation
_LOGGER.debug(f"Processing {count} items for {device_id}")
```

Never log sensitive data (secrets, tokens, passwords).

### Type Hints

All public APIs must have complete type hints:

```python
async def send_message(
    self,
    message: dict[str, Any],
    timeout: float = 30.0,
) -> bool:
    """Send a message."""
    ...
```

### Testing

Write tests for all new functionality:

```python
async def test_send_message_success(mock_websocket):
    """Test successful message sending."""
    session = TrestleSession(host="test", port=80)
    assert await session.send_message({"test": "data"})
```

Use descriptive test names and docstrings.

## Async Best Practices

- All I/O operations must be async
- Use `asyncio.gather()` for concurrent operations
- Set appropriate timeouts on all network calls
- Handle cancellation properly

## Questions?

Feel free to open an issue for any questions or discussions!
