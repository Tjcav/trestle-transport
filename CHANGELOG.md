# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Comprehensive development infrastructure (pre-commit, CI/CD, type checking)
- API documentation and architecture overview
- Enhanced package metadata and classifiers
- Version management and changelog

## [0.1.0] - 2026-01-09

### Added
- Initial release
- `TrestleSession` - High-level session manager for device communication
- `TrestleWsClient` - WebSocket client with reconnection support
- `TrestleHttpClient` - HTTP client for pairing, unpair, screenshots
- Protocol message builders and parsers
- Comprehensive error handling with custom exception hierarchy
- Support for protocol version 1
- Automatic batching of state updates
- Connection management and handshaking
- Protobuf message support (optional)

### Features
- Async/await throughout
- Full type hints
- >95% test coverage
- Python 3.11+ support
- Comprehensive logging

[Unreleased]: https://github.com/tjcav/trestle-transport/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/tjcav/trestle-transport/releases/tag/v0.1.0
