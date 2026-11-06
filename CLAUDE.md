<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **google-notebook-mcp** (2218 symbols, 3983 relationships, 134 execution flows).

> Index stale? Run `node .gitnexus/run.cjs analyze --index-only` from the project root — it auto-selects an available runner. No `.gitnexus/run.cjs` yet? Bootstrap with `npx`, `bunx`, or `pnpm dlx` — e.g. `bunx gitnexus@latest analyze` (npm 11 npx crash; #1939).

## Always Do

- **MUST run impact before editing.** Use `impact({target: "symbolName", direction: "upstream"})` or `node .gitnexus/run.cjs impact "symbolName" --direction upstream --repo .`; report callers, processes, and risk. Never substitute grep for graph analysis.
- **MUST analyze graph changes before committing.** Use `detect_changes({scope: "all"})` (MCP) or `node .gitnexus/run.cjs detect-changes --scope all --repo .` (CLI fallback). `partial: true` or `truncated: true` is not a clean check — a zero means unseen, not unaffected; re-run it. For regression review: `detect_changes({scope: "compare", base_ref: "main"})` or `node .gitnexus/run.cjs detect-changes --scope compare --base-ref "main" --repo .`.
- MUST warn on HIGH/CRITICAL `risk` pre-edit; never use `riskSharedAxes` to waive a HIGH/CRITICAL `risk` warning. Compare File/symbol: MCP File omits axes; Graph-RAG expands File.
- **MUST treat `risk: UNKNOWN` as unresolved, not as low.** An empty caller set is not evidence the symbol is unused — it can also mean the callers are not resolvable by the index (plain-object property access, dynamic dispatch, cross-language calls). `impact` pairs `UNKNOWN` with a `riskNote` saying so. Confirm with a text search before treating the symbol as safe to change or delete; do not proceed on the strength of a zero.
- **MUST use `query({search_query: "concept"})` for concepts/flows, `context({name: "symbolName"})` for a named symbol, or `impact` for blast radius, on read-only callers, dependencies, imports, or execution flow.** Graph first; text search only for empty/`UNKNOWN`/literals.
- For security review, `explain({target: "fileOrSymbol"})` lists taint findings (source→sink flows; needs `analyze --pdg`).

## Never Do

- NEVER edit a function, class, or method before MCP/CLI impact analysis.
- NEVER ignore HIGH or CRITICAL risk warnings from impact analysis, and never read `UNKNOWN` as an all-clear — it means the walk could not answer, which is the one verdict that requires confirming by other means.
- NEVER rename symbols with find-and-replace — use `rename` which understands the call graph.
- NEVER commit before MCP/CLI graph change analysis.

## Resources

| Resource | Use for |
| --- | --- |
| `gitnexus://repo/google-notebook-mcp/context` | Codebase overview, check index freshness |
| `gitnexus://repo/google-notebook-mcp/clusters` | All functional areas |
| `gitnexus://repo/google-notebook-mcp/processes` | All execution flows |
| `gitnexus://repo/google-notebook-mcp/process/{name}` | Step-by-step execution trace |

## CLI

| Task | Read this skill file |
| --- | --- |
| Understand architecture / "How does X work?" | `.claude/skills/gitnexus-exploring/SKILL.md` |
| Blast radius / "What breaks if I change X?" | `.claude/skills/gitnexus-impact-analysis/SKILL.md` |
| Trace bugs / "Why is X failing?" | `.claude/skills/gitnexus-debugging/SKILL.md` |
| Rename / extract / split / refactor | `.claude/skills/gitnexus-refactoring/SKILL.md` |
| Tools, resources, schema reference | `.claude/skills/gitnexus-guide/SKILL.md` |
| Index, status, clean, wiki CLI commands | `.claude/skills/gitnexus-cli/SKILL.md` |

<!-- gitnexus:end -->

# Google Gemini Notebook MCP Gateway — Claude Developer Guide

## Core Architecture
- **Zero Credential Export (DBSC / TPM Containment):** Session tokens (`SID`, `HSID`, `SSID`, `ya29.*`, `SNlM0e`) never leave Chrome's native memory. All outbound IPC data is sanitized via `secret_scrubber.py`.
- **Closed 9-Tool MCP Surface:** Strictly exposes `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, `delete_note`. All schemas enforce `additionalProperties: false` and `extra="forbid"`.
- **ADR-011 Interactive Session Lock:** Requires `select_notebook` prior to any notebook operations (`SESSION_UNLOCKED` guard). Once locked, subsequent calls with different IDs return `SESSION_LOCKED`.
- **Project Directory Binding (`.notebook_mcp.json`):** Remembers active notebook per workspace and prompts user with double-check confirmation at chat start.

## Common CLI & Developer Commands
```bash
# Automated 1-step onboarding
python3 install_and_onboard.py

# CLI Commands
gemini-notebook-mcp --help
gemini-notebook-mcp onboard       # Run onboarding wizard
gemini-notebook-mcp install       # Register native messaging manifest
gemini-notebook-mcp launch        # Launch dedicated Chrome & broker
gemini-notebook-mcp serve         # Run background broker daemon
gemini-notebook-mcp mcp           # Run MCP stdio facade
gemini-notebook-mcp allowlist seed# Interactive notebook allowlist wizard

# Code Quality & Testing
uv run ruff check .               # Linter
uv run mypy src/mcp_gateway --strict # Strict type checking
uv run pytest tests/ -v           # Full test suite (214 tests)
```

## Connecting Claude to the MCP Gateway

### Claude Desktop (`claude_desktop_config.json`)
- **macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows:** `%APPDATA%\Claude\claude_desktop_config.json`
- **Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "gemini-notebook": {
      "command": "uv",
      "args": [
        "--directory",
        "/absolute/path/to/google-notebook-mcp",
        "run",
        "gemini-notebook-mcp",
        "mcp"
      ],
      "env": {
        "UV_THREADPOOL_SIZE": "3"
      }
    }
  }
}
```

### Claude Code
```bash
claude mcp add gemini-notebook uv -- --directory /absolute/path/to/google-notebook-mcp run gemini-notebook-mcp mcp
```
