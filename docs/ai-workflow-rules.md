### AI Workflow Rules

#### Approach
* **Spec-Driven Incremental Implementation**: Implement against verified technical specifications and closed contracts. Do not guess, extrapolate, or invent product behavior or API endpoints.
* **Non-Destructive Context Preservation**: Maintain an append-only log of architectural decisions, protocol discoveries, and schema versions. Historical context must never be purged.
* **Zero-Trust Verification Protocol**: All claims, RPC IDs, and wire formats must be tagged with an evidence tier (`[DOCUMENTED]`, `[CODE-VERIFIED]`, `[MAINTAINER-OBSERVED]`, `[PROPOSED]`, `[UNVERIFIED]`). Any parameter tagged `[UNVERIFIED]` must fail closed defensively.

#### Scoping Rules
* **Strict Single-Unit Execution**: Work on exactly one architectural tier at a time (Host Bridge -> Extension -> Broker -> Tools).
* **Hermetic Offline Testing**: Validate each component against synthetic offline test fixtures before attempting integration with live browser sessions.
* **Do Not Mix Process Transports**: Never combine Native Messaging binary framing logic with MCP stdio JSON-RPC logic within the same module or process.

#### When to Split Work
Split an implementation unit if it combines any of the following:
* Native host binary framing with browser extension service worker messaging.
* Upstream Google batchexecute parsing with MCP JSON-RPC protocol serialization.
* File upload byte streaming with metadata readiness polling.
* Database schema migrations with business logic modifications.
If a component cannot be verified with a standalone unit test in under 30 seconds, the scope is too broad—split it immediately.

#### Handling Missing Requirements
* **No Speculative Synthesis**: Do not invent RPC methods (such as inventing a batchexecute query RPC `VfAZjd`). Natural language queries must strictly route to `GenerateFreeFormStreamed`.
* **Fail-Closed Fallback**: If a wire payload cannot be proven (such as native Google Drive positional arrays in `izAoDd`), enforce an explicit fail-closed fallback (download file bytes via browser and upload via Scotty `o4cbdc`).
* **Document and Escalate**: If an upstream protocol quirk or behavioral ambiguity is discovered, log it immediately in `progress-tracker.md` under Open Questions before proceeding.

#### Protected Files
Do not modify the following files unless explicitly directed by the project overseer:
* `src/mcp_gateway/storage/schema.sql` (Immutable database schema; modifications require explicit migration scripts).
* `tests/fixtures/golden_wire_captures.json` (Sanitized ground-truth protocol fixtures).
* Extension permissions block in `src/extension/manifest.json` (Scoped strictly to `nativeMessaging`, `scripting`, `tabs`; no broad cookie permissions).
* Concurrency and resource capping environment variables in profile baselines (`UV_THREADPOOL_SIZE=3`, zero swap).

#### Keeping Docs in Sync
Update the relevant documentation files whenever an implementation change occurs:
* Update `architecture.md` when system boundaries, IPC protocols, or data models change.
* Update `progress-tracker.md` after every completed milestone, newly uncovered protocol quirk, or architectural decision.
* Update `code-standards.md` if new linting rules, type invariants, or transport constraints are established.
* Update `project-overview.md` if user-facing features or success criteria are refined.

#### Before Moving to the Next Unit
1. The current unit passes all unit tests and synthetic wire fixtures.
2. No security invariant defined in `architecture.md` was violated (zero Google session credentials exported).
3. Type checking passes with zero errors (`mypy --strict` for Python; `tsc --noEmit` for TypeScript).
4. `progress-tracker.md` accurately reflects the completed work and defines concrete next steps.
