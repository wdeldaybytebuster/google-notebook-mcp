# Contributing to Google Notebook MCP

Thank you for your interest in contributing to **Google Notebook MCP**! We welcome contributions, bug fixes, documentation improvements, and feature proposals.

---

## Development Setup

### 1. Prerequisites
- Python 3.11+
- Google Chrome (Chrome 112+ or Chrome Beta)
- `uv` (recommended) or `pip`

### 2. Clone the Repository
```bash
git clone https://github.com/wdeldaybytebuster/google-notebook-mcp.git
cd google-notebook-mcp
```

### 3. Create Virtual Environment & Install Dependencies
```bash
# Using uv (recommended):
uv sync

# Or using standard venv:
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

---

## Code Quality & Standards

We enforce strict type safety, consistent code formatting, and robust automated test suites.

### 1. Strict Type Checking
All Python source code must pass strict `mypy`:
```bash
uv run mypy --strict src/
```

### 2. Code Linting & Formatting
We use `ruff` for fast linting and formatting:
```bash
uv run ruff check .
uv run ruff format --check .
```

### 3. Running Automated Tests
Run the test suite using `pytest`:
```bash
uv run pytest tests/ -v
```

---

## Architectural Rules for Contributors

When writing code or adding tools to this project:
1. **Zero Credential Export**: Google session tokens (`SID`, `HSID`, `SSID`, `ya29.*`, `SNlM0e`) must **never** cross IPC boundaries, be logged to stderr/stdout, or written to disk.
2. **Closed Schema Surface**: All MCP tool schemas must strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
3. **Conservative Mutation Journaling**: Any mutating operations must be journaled in the SQLite WAL state machine with idempotency keys. Ambiguous timeouts must never be automatically replayed.
4. **Hardware Capping**: Always respect thread pool limits (`UV_THREADPOOL_SIZE=3`) to prevent CPU starvation on constrained machines.

---

## Submitting Pull Requests

1. Fork the repository and create a feature branch (`git checkout -b feature/my-new-feature`).
2. Ensure all tests and linters pass cleanly.
3. Commit your changes using descriptive, conventional commit messages (`feat: ...`, `fix: ...`, `docs: ...`).
4. Push to your branch and submit a Pull Request.
5. Fill out the [Pull Request Template](.github/PULL_REQUEST_TEMPLATE.md) completely.
