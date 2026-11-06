# Consultation Part 1: Decoupled Schema & Config Isolation

## Question
For Phase 11 of the Google Notebook MCP roadmap (Zero-Friction Upstream Drift & Self-Healing Auto-Update Engine):
How should we architect the Decoupled Dynamic Schema and Adapter Layer to isolate volatile Google internal batchexecute RPC IDs (e.g., wXbhsf, rLM1Ne, CYK0Xb, o4cbdc) and positional array offsets from the core Python engine?
Specifically, how can these schema descriptors be loaded dynamically and how do we strictly guarantee that user personal configurations (such as allowlist.json, .notebook_mcp.json, and local credentials) remain completely untouched and air-gapped during updates?

## Answer
## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have formulated the architectural design for **Phase 11: The Decoupled Dynamic Schema and Adapter Layer**.

This architecture cleanly isolates volatile Google backend primitives (`batchexecute` RPC IDs like `wXbhsf`, `rLM1Ne`, `CYK0Xb`, `o4cbdc`, and their positional array layouts) from the static Python broker engine while enforcing an **Air-Gapped Personal Config Isolation Architecture**.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                                    (src/mcp_gateway/broker/)                                      |
|                                                                                                   |
|  +─────────────────────────────────────────────────────────────────────────────────────────────+  |
|  |                              IN-MEMORY ADAPTER SINGLETON                                     |  |
|  |  * Class: AdapterConfig (src/mcp_gateway/engine/adapters.py)                                 |  |
|  |  * Thread-Safe Hot Swap: async with self._session_mutex: self.adapter_config.reload()         |  |
|  +──────────────────────────────────────────────┬──────────────────────────────────────────────+  |
|                                                 │                                                 |
+─────────────────────────────────────────────────┼─────────────────────────────────────────────────+
                                                  │
                 ┌────────────────────────────────┴────────────────────────────────┐
                 │                                                                 │
                 ▼                                                                 ▼
+───────────────────────────────────────────────+ +─────────────────────────────────────────────────+
|      DYNAMIC ADAPTER DIRECTORY (MUTABLE)      | |     IMMUTABLE USER VAULT (STRICTLY AIR-GAPPED)   |
|     /workspace/scratch/adapters/              | |     ~/.config/notebooklm-mcp-bridge/            |
|                                               | |                                                 |
| ├── wire_spec.v4.json                         | | ├── allowlist.json (READ_ONLY vs INTERACTIVE)  |
| │   (RPC IDs, positional array maps, DOM tags)| | ├── .notebook_mcp.json (Workspace binding)     |
| ├── wire_spec.v4.json.sig                     | | ├── journal.db / WAL (Mutation transaction FSM) |
| │   (Ed25519 cryptographic signature payload) | | ├── capability_keys.json (OS pairing tokens)    |
| └── fallback_manifest.json                    | | └── client_ports.json (Local IPC socket pipe)   |
|     (Known-good backup specification)         | |                                                 |
|                                               | | * UPDATER PROCESS READ-ONLY / DENIED ACCESS     |
| * UPDATER PROCESS WRITE BOUNDARY              | | * NEVER OVERWRITTEN OR TOUCHED DURING UPDATES   |
+───────────────────────────────────────────────+ +─────────────────────────────────────────────────+
```

---

### A. Decoupled Dynamic Schema/Adapter Layer Architecture

To prevent backend updates from breaking core Python code, all positional array indices, method IDs, anti-XSSI prefixes, and DOM selectors are removed from executable source files and externalized into a declarative **Dynamic Wire Adapter Bundle** (`wire_spec.v4.json`).

#### 1. Wire Specification Descriptor Schema (`wire_spec.v4.json`)
```json
{
  "\$schema_version": "4.1.0",
  "min_broker_version": "3.1.0",
  "rpc_descriptors": {
    "list_notebooks": {
      "method_id": "wXbhsf",
      "request_template": "[[[\"wXbhsf\", \"[]\", null, \"generic\"]]]",
      "response_mapping": {
        "root_array_index": 0,
        "notebook_list_index": 0,
        "fields": { "id": 0, "title": 1, "source_count": 2, "updated_at_ms": 3 }
      }
    },
    "get_notebook_metadata": {
      "method_id": "rLM1Ne",
      "rows": {
        "source_catalog": { "row_index": 102, "fields": { "id": 0, "title": 1, "type": 2, "status": 3 } },
        "user_notes": { "row_index": 103, "fields": { "id": 0, "title": 1, "content": 2 } }
      }
    },
    "create_note": {
      "method_id": "CYK0Xb",
      "param_structure": "[\"{notebook_id}\", \"{title}\", \"{content}\"]"
    },
    "upload_intent": {
      "method_id": "o4cbdc",
      "unpack_depth": 2
    }
  },
  "dom_selectors": {
    "wiz_global_email": "window.WIZ_global_data.oM1Kwf",
    ## 1. Project Blueprint & Architectural State

As Chief Project Overseer and Lead Systems Architect for the **Google NotebookLM Model Context Protocol (MCP) Server** project (`google-notebook-mcp`), I have formulated the architectural design for **Phase 11: The Decoupled Dynamic Schema and Adapter Layer**.

This architecture cleanly isolates volatile Google backend primitives (`batchexecute` RPC IDs like `wXbhsf`, `rLM1Ne`, `CYK0Xb`, `o4cbdc`, and their positional array layouts) from the static Python broker engine while enforcing an **Air-Gapped Personal Config Isolation Architecture**.

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                TIER 2: LOCAL POLICY & SESSION BROKER                              |
|                                    (src/mcp_gateway/broker/)                                      |
|                                                                                                   |
|  +─────────────────────────────────────────────────────────────────────────────────────────────+  |
|  |                              IN-MEMORY ADAPTER SINGLETON                                     |  |
|  |  * Class: AdapterConfig (src/mcp_gateway/engine/adapters.py)                                 |  |
|  |  * Thread-Safe Hot Swap: async with self._session_mutex: self.adapter_config.reload()         |  |
|  +──────────────────────────────────────────────┬──────────────────────────────────────────────+  |
|                                                 │                                                 |
+─────────────────────────────────────────────────┼─────────────────────────────────────────────────+
                                                  │
                 ┌────────────────────────────────┴────────────────────────────────┐
                 │                                                                 │
                 ▼                                                                 ▼
+───────────────────────────────────────────────+ +─────────────────────────────────────────────────+
|      DYNAMIC ADAPTER DIRECTORY (MUTABLE)      | |     IMMUTABLE USER VAULT (STRICTLY AIR-GAPPED)   |
|     /workspace/scratch/adapters/              | |     ~/.config/notebooklm-mcp-bridge/            |
|                                               | |                                                 |
| ├── wire_spec.v4.json                         | | ├── allowlist.json (READ_ONLY vs INTERACTIVE)  |
| │   (RPC IDs, positional array maps, DOM tags)| | ├── .notebook_mcp.json (Workspace binding)     |
| ├── wire_spec.v4.json.sig                     | | ├── journal.db / WAL (Mutation transaction FSM) |
| │   (Ed25519 cryptographic signature payload) | | ├── capability_keys.json (OS pairing tokens)    |
| └── fallback_manifest.json                    | | └── client_ports.json (Local IPC socket pipe)   |
|     (Known-good backup specification)         | |                                                 |
|                                               | | * UPDATER PROCESS READ-ONLY / DENIED ACCESS     |
| * UPDATER PROCESS WRITE BOUNDARY              | | * NEVER OVERWRITTEN OR TOUCHED DURING UPDATES   |
+───────────────────────────────────────────────+ +─────────────────────────────────────────────────+
```

---

### A. Decoupled Dynamic Schema/Adapter Layer Architecture

To prevent backend updates from breaking core Python code, all positional array indices, method IDs, anti-XSSI prefixes, and DOM selectors are removed from executable source files and externalized into a declarative **Dynamic Wire Adapter Bundle** (`wire_spec.v4.json`).

#### 1. Wire Specification Descriptor Schema (`wire_spec.v4.json`)
```json
{
  "$schema_version": "4.1.0",
  "min_broker_version": "3.1.0",
  "rpc_descriptors": {
    "list_notebooks": {
      "method_id": "wXbhsf",
      "request_template": "[[[\"wXbhsf\", \"[]\", null, \"generic\"]]]",
      "response_mapping": {
        "root_array_index": 0,
        "notebook_list_index": 0,
        "fields": { "id": 0, "title": 1, "source_count": 2, "updated_at_ms": 3 }
      }
    },
    "get_notebook_metadata": {
      "method_id": "rLM1Ne",
      "rows": {
        "source_catalog": { "row_index": 102, "fields": { "id": 0, "title": 1, "type": 2, "status": 3 } },
        "user_notes": { "row_index": 103, "fields": { "id": 0, "title": 1, "content": 2 } }
      }
    },
    "create_note": {
      "method_id": "CYK0Xb",
      "param_structure": "[\"{notebook_id}\", \"{title}\", \"{content}\"]"
    },
    "upload_intent": {
      "method_id": "o4cbdc",
      "unpack_depth": 2
    }
  },
  "dom_selectors": {
    "wiz_global_email": "window.WIZ_global_data.oM1Kwf",
    "xsrf_token_variable": "SNlM0e"
  }
}
```

#### 2. Dynamic In-Memory Adapter Singleton (`adapters.py`)
The Python engine interacts with wire schemas exclusively through the `AdapterConfig` singleton (`src/mcp_gateway/engine/adapters.py`). 
* **Dynamic Resolution**: Code calls `AdapterConfig.get_rpc_mapping("list_notebooks")` rather than using hardcoded array indexes.
* **Hot Reloading**: When an updated adapter manifest is downloaded, `AdapterConfig.reload()` re-reads the JSON file and atomically replaces the active dictionary under an `asyncio` mutex lock:
  ```python
  async with self._session_mutex:
      self.adapter_config.reload_from_path(new_wire_spec_path)
  ```
* **RCE Prevention**: The adapter contains only declarative JSON parameters—never executable Python code (`.py` or compiled bytecode).

---

### B. Air-Gapped Personal Config Isolation Architecture

To satisfy our absolute user-data safety requirements, dynamic updates are strictly partitioned from personal user data at the OS filesystem boundary:

1. **Physical Filesystem Partitioning**:
   - **Immutable User Vault** (`~/.config/notebooklm-mcp-bridge/`): Contains `allowlist.json`, `.notebook_mcp.json`, `journal.db`, `capability_keys.json`, and socket configs.
   - **Dynamic Adapter Directory** (`/workspace/scratch/adapters/`): Contains exclusively `wire_spec.v4.json` and signature manifests.

2. **Access Control & Path Assertion Invariants**:
   - The background update worker (`update_agent.py`) is granted write handles **only** within `/workspace/scratch/adapters/`.
   - Path assertion guards in `src/mcp_gateway/storage/paths.py` enforce at runtime that any write operation attempting to target `~/.config/notebooklm-mcp-bridge/` raises a `SECURITY_VIOLATION` exception.
   - `allowlist.json` and `.notebook_mcp.json` are loaded into memory via dedicated file handles that are completely decoupled from `AdapterConfig`.

---

## 2. Research Audit: Verified Baseline vs. Discarded Findings

| Subsystem | Discarded Flaw / Anti-Pattern | Verified Production Baseline (Phase 11) | Architectural Grounding |
| :--- | :--- | :--- | :--- |
| **Upstream Schema Isolation** | Hardcoding positional array indices (e.g., `row[102]`) directly inside Python source files. | **Decoupled Declarative Wire Spec** (`wire_spec.v4.json`) parsed via `AdapterConfig` singleton. | **[APPROVED ARCHITECTURE]** Eliminates code deployment requirements when Google shifts backend array structures. |
| **Update Delivery Vehicle** | Downloading executable Python code (`.py` / `.whl`) remotely, exposing local machines to Remote Code Execution (RCE). | **Strict Declarative Data-Only Bundles**: Updates download signed JSON payloads containing only structural mappings. | **[SECURITY REQUIREMENT]** Guarantees zero code execution risk during automated background updates. |
| **Config Persistence** | Storing adapter mappings and user allowlists in a shared config file or directory. | **Strict Filesystem Partitioning**: User Vault (`~/.config/`) is physically separated from Adapters (`/scratch/adapters/`). | **[SECURITY REQUIREMENT]** Prevents auto-updaters from overwriting allowlists, workspace bindings, or SQLite databases. |
| **Hot Swap Synchronization** | Restarting the daemon process or modifying static files during active agent tool execution. | **Thread-Safe In-Memory Swap**: Mutex-guarded pointer replacement (`async with self._session_mutex:`). | **[CONCURRENCY REQUIREMENT]** Maintains active IPC socket connections without dropping stdio JSON-RPC streams. |

---

## 3. Gap Analysis & Risk Registry

```
+───────────────────────────────────────────────────────────────────────────────────────────────────+
|                                      TECHNICAL RISK REGISTRY                                      |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| Risk Domain         | Severity       | Likelihood  | Primary Failure Impact & Enforced Safeguard  |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 1. Personal Config  | CRITICAL       | LOW         | Updater overwrites allowlist.json or DB.     |
|    Destruction      |                |             | Safeguard: Immutable user vault directory    |
|                     |                |             | path separation (~/.config/... read-only).   |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 2. Malicious Update | CRITICAL       | LOW         | Compromised CDN delivers malicious wire spec.|
|    Injection        |                |             | Safeguard: Ed25519 signature validation      |
|                     |                |             | against hardcoded public key pin.            |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 3. Hot-Reload State | HIGH           | LOW         | Hot-reload during active query corrupts state|
|    Race Condition   |                |             | vector. Safeguard: Mutex-guarded reload      |
|                     |                |             | under self._session_mutex lock.              |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
| 4. Malformed Schema | HIGH           | MEDIUM      | Shifted Google RPC indices break parser.     |
|    Parse Failure    |                |             | Safeguard: M-05 Loud Canaries trip circuit   |
|                     |                |             | breaker and degrade to READ_ONLY mode.       |
+─────────────────────+────────────────+─────────────+──────────────────────────────────────────────+
```

---

## 4. Prioritized Action Items

To implement Phase 11, the engineering execution plan is divided into five sequential tasks:

- [ ] **Task 11.1: Build Decoupled Adapter Engine (`adapters.py` & `wire_spec.v4.json`)**
  - Extract all hardcoded `batchexecute` RPC IDs (`wXbhsf`, `rLM1Ne`, `CYK0Xb`, `o4cbdc`) and positional array indices into `src/mcp_gateway/engine/wire_spec.v4.json`.
  - Implement the `AdapterConfig` singleton in `src/mcp_gateway/engine/adapters.py`.

- [ ] **Task 11.2: Enforce Strict Filesystem Path Isolation**
  - Verify that user configuration paths (`~/.config/notebooklm-mcp-bridge/`) are strictly read-only for update modules.
  - Assert path containment invariants in `src/mcp_gateway/storage/paths.py`.

- [ ] **Task 11.3: Implement Ed25519 Signature Verification & Zero-Touch Fetcher**
  - Build `update_agent.py` to poll signed JSON adapter updates in the background.
  - Verify signatures using hardcoded `ED25519_PUBKEY_RELEASE_PIN` prior to staging files.

- [ ] **Task 11.4: Deploy Pre-Flight Canary Suite & Hot-Reload Mutex**
  - Integrate synthetic canary parsing (`test_canary_parse()`) to validate new adapter files before activation.
  - Wire atomic memory updates via `async with self._session_mutex:`.

- [ ] **Task 11.5: Verify Regression & Air-Gap Suite**
  - Add unit tests in `tests/test_adapter_isolation.py` proving that user allowlists and databases remain untouched during update execution.

---

💡 **Next Step**: You may now authorize the execution of Task 11.1 through Task 11.5. Let me know when you are ready to review the implementation code for `adapters.py`!

Citations count: 2452
