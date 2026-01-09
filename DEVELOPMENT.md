# Development Setup - trestle-coordinator-core

## Quick Start

```bash
# Install pre-commit hooks
pip install pre-commit
pre-commit install

# Run all quality checks
pre-commit run --all-files

# Run tests
pytest tests/ -v --cov=trestle_coordinator_core
```

## Configured Tools

### Automatic (During Editing in VS Code)
- **Pylance/Pyright** - Real-time type checking
- **Ruff** - Linting and formatting on save
- **Auto-imports** - Organize imports on save

### Pre-commit Hooks (Before Each Commit)
- **Ruff** - Linting and formatting
- **Mypy** - Type checking
- **Bandit** - Security scanning
- **YAML/JSON/TOML validation**
- **Trailing whitespace, EOF fixes**
- **Merge conflict detection**

### CI/CD (GitHub Actions)
- Runs on: Push to main, PRs
- Tests: Python 3.11, 3.12, 3.13
- Coverage reporting to Codecov

## Manual Commands

```bash
# Linting
ruff check trestle_coordinator_core/
ruff check trestle_coordinator_core/ --fix  # Auto-fix

# Formatting
ruff format trestle_coordinator_core/

# Type checking
mypy trestle_coordinator_core/

# Security scan
bandit -r trestle_coordinator_core/ -c pyproject.toml

# Tests with coverage
pytest tests/ --cov=trestle_coordinator_core --cov-report=html
```

## Configuration Files

| File | Purpose |
|------|---------|
| `ruff.toml` | Comprehensive linting rules (E, F, B, UP, D, ASYNC, S, etc.) |
| `pyrightconfig.json` | Type checking configuration |
| `pyproject.toml` | Pytest, Coverage, Bandit, Mypy config |
| `.pre-commit-config.yaml` | Pre-commit hook definitions |
| `.vscode/settings.json` | VS Code editor settings |
| `.github/workflows/ci.yml` | GitHub Actions CI pipeline |

## Excluded from Analysis

- `trestle_coordinator_core/trestle_pb2.py` - Generated protobuf code
- `trestle_coordinator_core/trestle_pb2.pyi` - Generated protobuf stubs

These are auto-generated and should not be manually edited.
