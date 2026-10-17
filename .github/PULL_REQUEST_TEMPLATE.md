## Description
Briefly describe the purpose of this change and what issue/feature it addresses.

## Type of Change
- [ ] Bug fix (non-breaking change which fixes an issue)
- [ ] New feature (non-breaking change which adds functionality)
- [ ] Breaking change (fix or feature that would cause existing schemas/behavior to change)
- [ ] Documentation update

## Checklist
- [ ] My code strictly adheres to the **Zero-Credential Export** invariant (no tokens or cookies logged or exported across IPC).
- [ ] All new or modified MCP tools enforce `extra="forbid"` and `additionalProperties: false`.
- [ ] All unit and integration tests pass: `pytest tests/ -v`.
- [ ] Strict type checking passes with zero errors: `mypy --strict src/`.
- [ ] Linting and formatting pass: `ruff check .` and `ruff format --check .`.
- [ ] Documentation has been updated to reflect any new parameters or behavior.
- [ ] No personal emails, local absolute filesystem paths, or test tokens are committed.
