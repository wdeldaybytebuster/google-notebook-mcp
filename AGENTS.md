<!-- gitnexus:start -->
# GitNexus — Code Intelligence

This project is indexed by GitNexus as **Google Notebook MCP** (451 symbols, 608 relationships, 10 execution flows).

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
| `gitnexus://repo/Google Notebook MCP/context` | Codebase overview, check index freshness |
| `gitnexus://repo/Google Notebook MCP/clusters` | All functional areas |
| `gitnexus://repo/Google Notebook MCP/processes` | All execution flows |
| `gitnexus://repo/Google Notebook MCP/process/{name}` | Step-by-step execution trace |

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

# Google Gemini Notebook MCP Gateway — Project Directives & Architectural Invariants

## I. Security Guardrails & Credential Containment
1. **Zero Credential Export (DBSC / TPM Runtime Containment):**
   - Google session tokens (`SID`, `HSID`, `SSID`, `ya29.*`, `SNlM0e`) MUST NEVER leave Chrome's native memory or cross IPC boundaries into agent logs, environment variables, or databases.
   - All outbound data crossing IPC boundaries must pass through `secret_scrubber.py`.
   - Never attempt direct external HTTP client impersonation of Google authentication outside the dedicated Chrome extension bridge.
2. **No Raw Shell Scripts:**
   - All automated processes, builds, and test runs must execute via controlled Python subprocesses or `node-pty`, never unmonitored raw shell scripts (`.sh`).
3. **Protect Transpiled Assets:**
   - Never edit transpiled build artifacts or generated files directly. Edit original TypeScript, JavaScript, and Python source files only.
4. **No Silent Code Stripping:**
   - Refactorings must preserve all existing security canaries, HMAC-SHA256 request hashing, mutation journaling, coordinate normalization, and native host bridge logic.

## II. Consolidated 5-Tool MCP Surface & Closed Schemas
1. **Strict 5-Tool Limit:** The MCP stdio facade (`broker.py mcp` / `gemini-notebook-mcp mcp`) strictly exposes only five tools:
   - `list_notebooks`: Decodes allowlisted notebooks via `wXbhsf` RPC records. Supports `page_size` and `cursor`.
   - `get_notebook_metadata`: Fetches full metadata via `rLM1Ne` RPC. Requires `notebook_id`.
   - `list_sources`: Extracts source records and readiness states directly from `rLM1Ne` row `[102]`. Supports `page_size` and `cursor`.
   - `query_notebook`: Streams grounded Q&A via `GenerateFreeFormStreamed` with normalized Unicode citation offsets. Requires `notebook_id`, `question`, and `request_key`.
   - `add_source`: Ingests content via polymorphic payloads (`izAoDd` for text/url/youtube/drive; Scotty for files). Requires `notebook_id`, `idempotency_key`, and `source`.
2. **Closed Schema Invariant:**
   - All tool schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - Any unrecognized parameter must immediately return an `INVALID_ARGUMENT` error envelope.
3. **Standard Failure Envelope Contract:**
   - All errors across tools and IPC must conform to:
     ```json
     {
       "ok": false,
       "error": {
         "code": "ALLOWLIST_DENIED | AUTH_REQUIRED | MUTATION_UNKNOWN | INVALID_ARGUMENT | INTERNAL | NOT_FOUND",
         "message": "Descriptive message",
         "retryable": false
       }
     }
     ```

## III. Scotty 3-Step Resumable Upload Protocol
Binary file ingestion via `add_source` (`source.type == "file"`) must follow the verified 3-step sequence:
1. **Intent Registration:** Call `o4cbdc` RPC payload `[[[filename]], notebook_id, [58]]` to acquire the server-assigned `sourceId`.
2. **Session Creation:** Execute in-browser MV3 fetch to `/upload/_/LabsTailwindUi/...` with headers `X-Goog-Upload-Command: start`, `X-Goog-Upload-Protocol: resumable`, and JSON payload `{ PROJECT_ID: notebook_id, SOURCE_NAME: filename, SOURCE_ID: sourceId }`. Extract session URL from `x-goog-upload-url`.
3. **Finalize Byte Stream:** Stream raw file bytes directly to the session URL with headers `X-Goog-Upload-Command: upload, finalize` and `X-Goog-Upload-Offset: 0`.

## IV. Full Jitter Exponential Backoff Readiness Polling
When `add_source` is invoked with `wait_until_ready=true`:
1. The engine polls `rLM1Ne` and inspects row `[102]`, index `4` readiness enum (`PROCESSING = 1`, `READY = 2`, `ERROR / FAILED = 3`).
2. Sleep intervals use Full Jitter Backoff:
   `delay = random.uniform(0, min(base_delay * 2**attempt, max_delay))`
3. State transitions:
   - `READY (2)` -> Confirms mutation in journal, returns success.
   - `ERROR / FAILED (3)` -> Marks mutation `REJECTED`, returns `INTERNAL` error envelope.
   - Timeout / Disconnect -> Marks mutation `UNKNOWN` (`MUTATION_UNKNOWN`), freezing automatic replay.

## V. Mutation Journaling & Unknown State Freeze
1. Every write mutation (`add_source`, `query_notebook`) follows:
   `PREPARED -> SENT -> CONFIRMED | REJECTED`
2. **Freeze on Ambiguity:** If a mutation disconnects or times out during transmission or readiness polling, it transitions to `UNKNOWN`. Automatic replay of `UNKNOWN` or `SENT` records is strictly blocked until resolved via human or deterministic active reconciliation.

## VI. UTF-16 to Unicode Citation Normalization
1. Backend streaming citations return offsets indexed by JavaScript UTF-16 code units.
2. The gateway must normalize these to Unicode character spans (`start_char`, `end_char`) against the full decoded text to eliminate drift caused by astral plane characters (emojis, math symbols).

## VII. Hardware & Host Execution Bounds (Lenovo Chromebook Edge Profile)
1. **Memory & Concurrency:**
   - Prefix Node/npm invocations with `NODE_OPTIONS="--max-old-space-size=1024"`.
   - Set `UV_THREADPOOL_SIZE=3` in environment variables.
   - Cap test runner concurrency (`--maxWorkers=4`).
   - Run background build and test commands sequentially to prevent `earlyoom` eviction.
2. **Browser Native Bridge:**
   - Chrome automation must point directly to `/usr/bin/google-chrome-beta` to bypass Garcon loopback bridging interference.
