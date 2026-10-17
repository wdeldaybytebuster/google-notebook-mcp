## 1\. Project Blueprint & Architectural State

The Google Gemini Notebook Model Context Protocol (MCP) gateway architecture is organized into four foundational pillars, establishing a zero-trust, browser-resident execution bridge between AI coding assistants (Claude Code, Cursor, Cline, Windsurf) and private NotebookLM knowledge bases 1-4.  
\+---------------------------------------------------------------------------------------------------+  
|                                   AI CODING AGENTS (IDE / CLI)                                    |  
|                          Claude Code  \*  Cursor  \*  Cline  \*  Windsurf                            |  
|                                    \[Transport: stdio JSON-RPC 2.0\]                                |  
\+-------------------------------------------------+-------------------------------------------------+  
                                                  |  
                                                  v  
\+---------------------------------------------------------------------------------------------------+  
|                               LOCAL POLICY & SESSION BROKER (DAEMON)                              |  
|  \* Process Facade: stdio JSON-RPC 2.0 engine (protocol-only on stdout; diagnostic logging stderr) \[1, 5\]  
|  \* Mandatory Allowlist Enforcement (\~/.config/notebooklm-mcp-bridge/allowlist.json) \[5, 6\]    |  
|  \* Conservative SQLite Mutation Journal: prepared \-\> sent \-\> confirmed / rejected / unknown \[7, 8\]  
|  \* Consolidated 9-Tool Closed JSON Schema Surface (list\_notebooks, select\_notebook, ...) \[9, 10\]|  
|  \* Host Governance Caps: UV\_THREADPOOL\_SIZE=3, ulimit \-n 65536, zero unencrypted storage \[11, 12\]|  
\+-------------------------------------------------+-------------------------------------------------+  
                                                  |  
                    \[Local IPC: Unix Domain Socket / Named Pipe (Big-Endian 32-bit Framing)\] \[1, 5\]  
                                                  |  
                                                  v  
\+---------------------------------------------------------------------------------------------------+  
|                                  DEDICATED NATIVE MESSAGING HOST                                  |  
|  \* Standalone Native OS Process (Decouples 32-bit Binary Framing from MCP Stdio) \[1, 13\]          |  
|  \* Protocol Relaying: Chrome Native 32-bit Native-Endian \<-\> Broker IPC 32-bit Big-Endian \[5, 14\]|  
|  \* Chunk Segmentation: Enforces \<1 MiB Host-to-Extension Limit via \~512 KiB Slices \[15, 16\]    |  
|  \* Strict Origin Whitelisting: Validates extension ID in manifest; checks SO\_PEERCRED \[1, 5\]    |  
\+-------------------------------------------------+-------------------------------------------------+  
                                                  |  
                 \[Chrome Native Messaging API: 32-bit Native-Endian Binary Frames\] \[1, 14\]  
                                                  |  
                                                  v  
\+---------------------------------------------------------------------------------------------------+  
|                              BROWSER COMPANION (MANIFEST V3 EXTENSION)                            |  
|  \* Execution Target: Injected page-main.js running in MAIN-world on notebook.google.com \[1, 17\]   |  
|  \* Runtime Authentication: Extracts page-resident SNlM0e (CSRF 'at') & FdrFJe (f.sid) \[17, 18\]    |  
|  \* Network Execution: In-Browser fetch() Retains Cookies & Hardware TPM DBSC Keys \[1, 14, 17\]     |  
|  \* Zero Secret Leakage: Cookies, CSRF tokens, and raw headers never cross IPC to MCP \[19, 20\]   |  
\+---------------------------------+---------------------------------+-------------------------------+  
                                  |                                 |  
                 \[batchexecute Form POST RPC\] \[21\]  \[Server-Streaming gRPC-Web POST\] \[22\]  
                                  |                                 |  
                                  v                                 v  
\+---------------------------------------------------+ \+---------------------------------------------+  
|              BATCHEXECUTE RPC ENDPOINT            | |          STREAMING QUERY ENDPOINT           |  
| POST /\_/LabsTailwindUi/data/batchexecute \[21\]      | | POST /\_/LabsTailwindUi/data/.../            |  
| \* Envelope: f.req=\[\[\['RPC\_ID', JSON, null, 'gen'\]| |      GenerateFreeFormStreamed \[22\]          |  
| \* Strips )\]}' Anti-XSSI Prefix \[21\]                | | \* Chunked Stream \+ Inline Anchors \[23\]      |  
| \* Methods: wXbhsf, rLM1Ne, izAoDd, o4cbdc \[24\]     | | \* Isolated HTTP Jar (Prevents 401\) \[25\]    |  
\+---------------------------------+-----------------+ \+---------------------------------------------+  
                                  |  
                        \[Scotty Intent o4cbdc\] \[26\]  
                                  v  
\+---------------------------------------------------+  
|               SCOTTY RESUMABLE UPLOAD             |  
| POST /upload/\_/ (x-goog-upload-command: start) \[26\]|  
| \* Session URL Retained Strictly in Page Context \[7|  
| \* Raw Bytes Streamed to x-goog-upload-url \[26, 27\]|  
\+---------------------------------------------------+

### Pillar A: Authentication & Session Strategy

* **Browser-Resident Execution Broker**: All consumer interactions execute within the authenticated browser context via an unpacked Chrome Manifest V3 companion extension injecting into the **MAIN world** of notebook.google.com 1, 4, 17\. In-browser fetch() calls delegate session authentication directly to Chrome's native network stack, automatically satisfying Device Bound Session Credentials (DBSC) and hardware Trusted Platform Module (TPM) challenge signing without exporting credentials 1, 4, 14, 17\.  
* **Zero Credential Export Invariant**: Raw Google session cookies (SID, HSID, SSID, \_\_Secure-1PSID, \_\_Secure-1PSIDTS, SAPISID), Google access tokens (ya29...), Android master tokens (gpsoauth), and CSRF tokens (SNlM0e / at) **never leave the browser's sandbox** 4, 18-20, 28\. They are never written to disk, passed across local sockets, or exposed to the MCP client 19, 20\.  
* **Cold-Start Tab Provisioning**: Because Manifest V3 service workers have no DOM access and cannot read window.WIZ\_global\_data directly, the extension background worker dynamically provisions a pinned background tab to https\://notebook.google.com/, awaits DOM hydration and WIZ\_global\_data.SNlM0e population, and injects page-main.js into the MAIN world 14, 29-31. User-owned tabs remain open, while extension-created tabs are recycled after a 60-second cooldown 14, 30\.  
* **Multi-Account URL Routing**: In multi-profile browser sessions, the bridge dynamically extracts the account routing prefix /u/{N}/ from the active tab URL path, appends authuser={N} query parameters on batchexecute URLs, passes x-goog-authuser: {N} on Scotty uploads, and verifies window.WIZ\_global\_data.oM1Kwf against the user's expected email address to prevent silent, dangerous fallbacks to account 0 17, 18, 32-34.

### Pillar B: Protocol & Transport Topology

1. **Transport Process Isolation**: Chrome Native Messaging enforces a **32-bit native-byte-order length-prefixed binary framing format** across standard I/O 1, 5, 14\. Because MCP communicates via **newline-delimited JSON-RPC 2.0 on stdio**, these protocols cannot share a process 1, 5, 13\. The architecture strictly separates them: a dedicated Native Messaging host binary relays traffic over an authenticated local Unix domain socket (or Windows named pipe) using big-endian 32-bit framing to the standalone MCP policy broker daemon 1, 5, 13\.  
2. **Dual Endpoint Routing & Cookie Jar Isolation**: The gateway maintains strict transport isolation across two distinct upstream Google communication paths 1, 2, 25:  
3. *Metadata, Ingestion, & Management*: Dispatched through the positional batchexecute envelope (POST /\_/LabsTailwindUi/data/batchexecute) transmitting URL-encoded f.req form arrays 17, 21\.  
4. *Grounded Querying*: Dispatched to the dedicated server-streaming gRPC endpoint (POST /\_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed) 22, 25\. In headless fallback mode, this endpoint must use an **isolated HTTP client cookie jar** to prevent session poisoning and HTTP 401 failures caused by batchexecute Set-Cookie responses 25\.

### Pillar C: Consolidated 9-Tool MCP Surface

The external tool surface exposed to LLM coding agents is strictly consolidated into nine closed JSON schemas (additionalProperties: false, extra="forbid") to eliminate context window bloat and tool-selection hallucinations 4, 9, 10, 35:

1. **select\_notebook**: Enforces ADR-011 single-notebook session lock (`notebook_id` or `title`). Supports `save_for_project: bool = True` to save selection to `.notebook_mcp.json` in project root. Serialized via `_session_mutex` (M-01). Transitions from `DISCOVERY_ONLY` to `ACTIVE_DISPATCH`.  
2. **list\_notebooks**: Ingests optional snapshot pagination arguments (page\_size, cursor) and returns visible, allowlisted notebooks decoded from wXbhsf response rows. When locked, filters results to the active notebook. Inspects `.notebook_mcp.json` to return `project_config` and an actionable `user_prompt` directing the AI assistant to double-check selection with the user at the start of each chat.  
3. **get\_notebook\_metadata**: Decodes comprehensive metadata for the approved locked notebook from the rLM1Ne row shape.  
4. **list\_sources**: Extracts normalized source records and readiness states directly from notebook metadata returned by rLM1Ne row [102].  
5. **query\_notebook**: Submits natural language queries (question, request\_key, optional source\_ids) to GenerateFreeFormStreamed, returning answers with verified citation spans. Enforces strict citation grounding barrier (M-06), scoped readiness (M-10), and mid-stream error deltas (P-01). Preserves un-hashed `_meta.mcp_correlation_id` (P-04).  
6. **add\_source**: Ingests knowledge via polymorphic payloads (text, url, youtube, drive, file) backed by broker-side idempotency verification, pre-flight email guard (P-03), and Full Jitter Exponential Backoff polling.  
7. **create\_note**: Creates user note via CYK0Xb RPC (title, content, idempotency\_key). Journaled in SQLite FSM.  
8. **list\_notes**: Extracts user notes from rLM1Ne row [0][17]. Enforces loud failure canary (`UPSTREAM_SCHEMA_DRIFT`) on array shape drift (M-05).  
9. **delete\_note**: Deletes user note via tGMBJ RPC (note\_id, idempotency\_key). Journaled in SQLite FSM.  

All tools enforce closed schemas and emit standard structured failure envelopes ({ "ok": false, "error": { "code", "message", "retryable" } }).

### Pillar D: Security Invariants, Mutation Journaling, & Edge Governance

* **Capability Keystore Isolation**: The local OS vault stores only local capability keys and extension pairing secrets 1, 20\. Secret storage uses Python keyring with a strict backend allowlist (macOS Keychain, Windows Credential Locker, Freedesktop Secret Service) 1, 44\. atom/node-keytar is deprecated and strictly rejected 28, 44\.  
* **Conservative Mutation Journaling**: All write operations (add\_source, query\_notebook) mandate a client-supplied key (idempotency\_key / request\_key) tracked within an SQLite state machine (prepared \-\> sent \-\> confirmed / rejected / unknown) backed by HMAC-SHA256 request hashing 4, 7, 8, 45\. Ambiguous timeouts after transmission are journaled as unknown and are **never automatically replayed** 6, 46\.  
* **Resource Governance**: To guarantee host stability on resource-constrained development nodes (such as the verified 8-core Gracemont Intel Core i3-N305 baseline), the broker runtime enforces concurrency and memory ceilings: UV\_THREADPOOL\_SIZE=3, ulimit \-n 65536, NODE\_OPTIONS="--max-old-space-size=1024", and strict loopback socket binding (\[suspicious link removed\]) 11, 12, 47\.

## 2\. Research Audit: Verified Baseline vs. Discarded Findings

Technical parameters and claims across all notebook sources have been audited against the project's five-tier evidentiary standard: **DOCUMENTED**, **CODE-VERIFIED**, **MAINTAINER-OBSERVED**, **PROPOSED**, and **UNVERIFIED** 48\.  
Architectural Domain,Research Claim / Pattern,Evidence Tier,Audit Verdict & Technical Grounding  
Authentication,"Direct on-disk SQLite cookie extraction (auth.json, raw SQLite reads) 44.",Discarded (Anti-Pattern) 28,"Rejected. Windows Chrome 127+ and macOS 130+ enforce App-Bound Encryption (ABE) 28, 44\. Keys in Local State are wrapped in DPAPI blobs decryptable only by legitimate Chrome processes via elevation\_service COM RPC (IElevator::DecryptData) 44, 49, 50\. Device Bound Session Credentials (DBSC) bind sessions to TPM hardware keys, causing headless external readers to fail 28, 44."  
Authentication,"Public third-party OAuth 2.0 access (ya29... bearer tokens) 44, 51.",Discarded (Disproved) 28,"Rejected. No public OAuth scope exists for consumer NotebookLM in Google’s scope catalog 52\. Submitting ya29 access tokens returns HTTP 403 Forbidden 28, 51, 52."  
Authentication,"Android mobile gRPC backend (notebooklm-pa.googleapis.com:443) 53, 54.","Code-Verified (Restricted) 53, 54","Excluded from Default. While notebooklm-py verifies an internal mobile backend authorized via labs-tailwind scopes using gpsoauth, this requires extracting an account-wide Google Master Token, introducing severe account-takeover risks 53-55."  
Authentication,"Browser-resident execution via Manifest V3 extension 1, 44.",Code-Verified / Proposed 44,"Adopted as Baseline. Verified in notebooklm-mcp-bridge reference code 5, 15\. Preserves native browser DBSC challenge signing and automatic session renewal without exporting credentials 1, 14, 17, 44."  
Transport,Shared stdout across Chrome Native Messaging and MCP JSON-RPC 44.,Discarded (Anti-Pattern) 44,"Rejected. Chrome Native Messaging requires 32-bit native-byte-order binary length-prefixed frames; MCP requires newline-delimited JSON-RPC 1, 5, 14, 44\. Sharing a process corrupts both transports 44."  
Transport,"Independent Native Host binary bridging to MCP Daemon via Local IPC 1, 44.",Code-Verified / Proposed 44,"Adopted as Baseline. The native host reads/writes 32-bit binary frames, forwarding messages over Unix domain sockets or named pipes using big-endian 32-bit framing 1, 5, 14, 44."  
Query Protocol,"VfAZjd is the batchexecute RPC ID for natural language querying 28, 44.","Discarded (Disproved) 28, 44","Rejected. Forensic network trace and code audits confirm that natural language querying does not use the batchexecute envelope 28, 44\. Querying routes to GenerateFreeFormStreamed 22, 28, 44."  
Query Protocol,"Server-streaming GenerateFreeFormStreamed endpoint 22, 44.","Code-Verified 22, 44","Adopted as Baseline. Verified across teng-lin/notebooklm-py commit 3665ca5 and notebooklm-mcp-bridge 22, 44, 56\. Emits chunked text records and structured citation coordinate blocks 23, 41, 44."  
Query Protocol,Isolated HTTP client cookie jar for query streaming 44.,Maintainer-Observed 44,"Adopted as Baseline. Documented in jacob-bd/notebooklm-mcp-cli Issue \#187: executing batchexecute returns Set-Cookie headers that poison shared client jars, causing subsequent streaming queries to fail with HTTP 401 44, 57."  
RPC Registry,"wXbhsf (List Notebooks) 24, 44.","Code-Verified 24, 44","Adopted as Baseline. Payload \[null, 1, null, \[58\]\] or \[null, 1, null, \[28\]\] returns title row, embedded sources row\[48\], notebook ID row\[28\], role row\[21\], and created/viewed timestamps 24, 56, 59."  
RPC Registry,"rLM1Ne (Get Notebook Metadata & Ingested Sources) 24, 44.","Code-Verified 24, 44","Adopted as Baseline. Payload \[notebook\_id, null, OPTS, null, 0\] with URL parameter source-path: /notebook/{id} returns complete notebook metadata and embedded sources in row \[39\] 24, 56, 60, 61."  
RPC Registry,"hizoJc is list\_sources 28, 44.","Discarded (Disproved) 28, 44","Corrected. Inspection of pinned notebooklm-py and notebooklm-mcp-bridge confirms hizoJc is GET\_SOURCE (\[\[""source\_id""\],\]), NOT list\_sources 28, 44, 62\. Source listing is extracted from notebook metadata returned by rLM1Ne 28, 44, 62."  
RPC Registry Discrepancy,"ozz5Z is an alternate URL-add cohort ID 28, 44.","Discarded (Contradicted) 28, 44","Corrected. Source audit of pinned notebooklm-py commit 3665ca5 confirms ozz5Z is GET\_USER\_TIER in the reference codebase, NOT an add-source RPC 24, 28, 62\. URL/text addition routes exclusively through izAoDd 24, 42, 56."  
RPC Registry,"izAoDd (Add URL / Text / Drive Source) 24, 42, 44.","Code-Verified 24, 42, 44","Adopted as Baseline. Positional array \[\[\[null, null, \[url\], ... 1\]\], id, \[58\]\] handles URLs; \[null, \[title, content\], null, 2\] handles pasted text 42, 56, 63, 64\. Unified under izAoDd 42."  
File Ingestion,Single-step POST or DOM file injection 44.,Discarded (Anti-Pattern) 44,"Rejected. Fragile, undocumented, and breaks on binary payloads 44."  
File Ingestion,"Scotty 3-Step Resumable Upload Pipeline 26, 44.","Code-Verified 26, 44","Adopted as Baseline. Verified from icebear0828/notebooklm-client PR \#3 and source-lm-extension: (1) Register intent via o4cbdc to obtain sourceId; (2) POST /upload/\_/ (x-goog-upload-command: start) to obtain session URL; (3) Stream bytes to x-goog-upload-url (upload, finalize) 26, 44, 65."  
Credential Keystore,"Integration via atom/node-keytar 28, 44.","Discarded (Deprecated) 28, 44","Rejected. atom/node-keytar was officially archived in December 2022 28, 44, 66\. Production systems must use Python keyring with an explicit backend allowlist or native platform bindings 28, 44."  
Enterprise Cloud Route,Assuming Enterprise REST parity with Consumer Chat 44.,"Documented (Restricted) 44, 67","Dual-Adapter Separation. Documented under Google Cloud Discovery Engine v1alpha for notebook and source management, but chat endpoints are completely absent from the official REST API 44, 67, 68."

## 3\. Gap Analysis & Risk Registry

Critical architectural gaps and high-complexity integration hurdles have been systematically investigated and resolved across the project dossier:  
\+---------------------------------------------------------------------------------------------------+  
|                                      TECHNICAL RISK REGISTRY                                      |  
\+---------------------+----------------+-------------+----------------------------------------------+  
| Identified Gap      | Severity       | Likelihood  | Primary Failure Impact & Mitigation          |  
\+---------------------+----------------+-------------+----------------------------------------------+  
| 1\. Google Drive     | HIGH           | MEDIUM      | izAoDd positional array unverified \[42\].      |  
|    Wire Format      |                |             | Mitigation: Fail-closed Scotty fallback \[9,15|  
\+---------------------+----------------+-------------+----------------------------------------------+  
| 2\. Streaming Query  | HIGH           | LOW         | Nested source IDs or chat continuity tokens  |  
|    Wire Options     |                |             | misformatted. Mitigation: Triple-nested      |  
|                     |                |             | arrays and hPTbtc session UUIDs \[41, 69, 70\].|  
\+---------------------+----------------+-------------+----------------------------------------------+  
| 3\. Citation Bound   | MEDIUM         | HIGH        | UTF-16 surrogate pairs in astral plane cause |  
|    Geometry         |                |             | Python string slicing misalignments \[71\].   |  
|                     |                |             | Mitigation: Byte-level UTF-16 decoding \[72\].|  
\+---------------------+----------------+-------------+----------------------------------------------+  
| 4\. MV3 Lifecycle &  | HIGH           | MEDIUM      | Service worker idle timeout or missing tab   |  
|    Cold Starts      |                |             | drops native messages \[29\]. Mitigation:      |  
|                     |                |             | Pinned background tab \+ keep-alive alarm \[30\]|  
\+---------------------+----------------+-------------+----------------------------------------------+  
| 5\. Multi-Account    | MEDIUM         | HIGH        | Hardcoded /u/0/ causes HTTP 400 / CSRF error |  
|    URL Routing      |                |             | on secondary profiles \[73\]. Mitigation:     |  
|                     |                |             | Dynamic authuser extraction \+ oM1Kwf check \[2|  
\+---------------------+----------------+-------------+----------------------------------------------+  
| 6\. Source Polling   | MEDIUM         | LOW         | Premature query execution while source index |  
|    Enums & Readines |                |             | state is PROCESSING \[74\]. Mitigation: Full   |  
|                     |                |             | Jitter Exponential Backoff polling \[75, 76\]. |  
\+---------------------+----------------+-------------+----------------------------------------------+

### Detailed Gap Resolutions & Technical Grounding

#### Gap 1: Google Drive Ingestion Wire Protocol

1. **Evidence Tier**: \[CODE-VERIFIED\] (RPC ID confirmed) / \[UNVERIFIED\] (Drive-specific positional parameters) 42\.  
2. **Technical Reality**: Google unifies all standard URL, pasted text, YouTube, and Google Drive source ingestions under the single izAoDd RPC method 42\. There is **no dedicated Drive RPC** 42\. However, the exact Drive positional array was not captured during the Gemini-3.5 wire-shape migration 42, 77, 78\.  
3. **Resolved Implementation**: Adopt a fail-closed execution strategy:  
4. Attempt native Drive import via izAoDd using the proposed 4-level nested array structure: \[\[\[\[doc\_id, mime\_type, 1, title\]\]\], notebook\_id, \[58\]\] 64, 79, 80\.  
5. If the endpoint returns an HTTP 400 or RPC error frame, trigger the **Scotty 3-Step Fallback**: the browser companion fetches the Drive file bytes via authenticated fetch() and registers/streams the bytes via the o4cbdc resumable upload pipeline 81, 82\.

#### Gap 2: GenerateFreeFormStreamed Wire Request Schema & Chat History

* **Evidence Tier**: \[CODE-VERIFIED\] (Protobuf fields from Android APK) / \[MAINTAINER-OBSERVED\] (Wire encoding) 22\.  
* **Wire Body Format**: URL-encoded form parameters: f.req=\[null, "{params\_json}"\]\&at={CSRF\_TOKEN} 22, 83\.  
* **Params JSON Structure**:  
* \[  
*   \[ \[\[source\_id\_1\]\], \[\[source\_id\_2\]\] \], //  Sources: triple-nested (nest\_source\_ids(ids, 2))  
*   "User query string",                  // \[48\] user\_query  
*   \[ \[answer, null, 2\], \[query, null, 1\] \], // \[28\] conversation\_history: newest-first alternating  
*   \[ null, null, null, null, 120 \],      // \[1\] request\_context options (verbosity=120)  
*   "chat\_session\_id\_or\_null",            // \[2\] Server conversation UUID (from hPTbtc) or null  
*   "client\_generated\_message\_uuid",      // \[21\] Unique message UUID  
*   null,                                 // \[24\] Reserved  
*   "notebook\_id\_uuid",                   // \[26\] Target Notebook UUID  
*   1                                     // \[42\] Origin: QUERY\_ORIGIN\_CHAT\_TEXT\_BOX \= 1  
* \]  
* *(Verified across Source 5 Section 3.2 41, Source 6 Section 2.2.2 84, and Source 4 Section 1.2 85).*  
* **Conversation Continuity Reconciliation**: Pinned issue analysis confirms that the session\_id in AnswerResponse.conversationTurnKey is merely a per-stream identifier 70\. The durable conversation ID must be retrieved via hPTbtc (\[\[2, null, null, \[1, null...\]\], null, notebook\_id, 20\]) and supplied to subsequent turns, accompanied by locally cached turns in params\[28\] 69, 70\.

#### Gap 3: Citation Coordinate Geometry & Normalization

* **Evidence Tier**: \[CODE-VERIFIED\] (Protobuf fields & V8 slicing semantics) 71\.  
* **Technical Reality**: Google's backend computes coordinate arithmetic (start\_char, end\_char) based on **UTF-16 code units** (V8 JavaScript convention) indexing the source document's parsed chunked text, **not** the generated answer text 71\. When text contains astral-plane characters (emojis, mathematical symbols), a single Unicode code point requires two UTF-16 code units (a surrogate pair), causing Python code-point slicing to misalign 71\.  
* **Resolved Implementation**: The broker normalization engine implements a translation layer converting UTF-16 code unit offsets to native Python Unicode offsets 72:  
* def utf16\_to\_unicode\_offset(text: str, utf16\_offset: int) \-\> int:  
*     utf16\_bytes \= text.encode('utf-16-le')  
*     sliced\_bytes \= utf16\_bytes\[:utf16\_offset \* 2\]  
*     return len(sliced\_bytes.decode('utf-16-le', errors='replace'))  
* *(Verified in Source 5 Section 4.4 72, Source 6 Section 2.3.3 86, and Source 4 Section 2.2 87).*

#### Gap 4: Manifest V3 Cold-Start Lifecycle & Background Execution

1. **Evidence Tier**: \[DOCUMENTED\] (Chromium MV3 APIs) / \[PROPOSED\] (Tab provisioning flow) 88\.  
2. **Technical Reality**: MV3 service workers have no DOM access, cannot read window.WIZ\_global\_data, and terminate after \~30 seconds of inactivity 29, 88\. Offscreen documents cannot be used because they lack authenticated session context 14, 29\.  
3. **Resolved Implementation**:  
4. Service worker wakes on native message from the host 30, 89\.  
5. Queries for an open tab matching https\://notebook.google.com/\*; if absent, creates an active-false pinned tab 30, 31\.  
6. Awaits DOM hydration and checks for window.WIZ\_global\_data.SNlM0e 30, 31\.  
7. Injects page-main.js into the **MAIN world** via chrome.scripting.executeScript 30, 31\.  
8. Keeps the service worker alive via chrome.alarms firing every 30 seconds 14, 89\.  
9. Recycles self-created tabs after a 60-second cooldown while keeping user tabs untouched 14, 30\.

#### Gap 5: Multi-Account URL Routing & User Index Isolation

1. **Evidence Tier**: \[CODE-VERIFIED\] (notebooklm-py PR \#364) / \[MAINTAINER-OBSERVED\] 32, 73\.  
2. **Technical Reality**: In multi-account browser sessions, Chrome segments identities using /u/{N}/ path prefixes and the authuser={N} query parameter 73\. Invoking account 0 endpoints from an account 1 context triggers HTTP 400 or CSRF rejections 90\. If N exceeds account count, Google silently falls back to authuser=0, creating a cross-account data leak risk 91, 92\.  
3. **Resolved Implementation**:  
4. Extract authuser dynamically from window.location.pathname.match(/\\/u\\/(\\d+)\\/) 17, 89\.  
5. Append authuser={N} on batchexecute URLs (omitted when "0") 17, 33, 34\.  
6. Pass x-goog-authuser: {N} headers on Scotty upload requests 32, 34, 90\.  
7. Verify window.WIZ\_global\_data.oM1Kwf against the user's expected account email; fail closed with PERMISSION\_DENIED on mismatch 18, 34, 91, 92\.

#### Gap 6: Source Ingestion Readiness Enums & Polling Engine

* **Evidence Tier**: \[CODE-VERIFIED\] (notebooklm-py commit 3665ca5) / \[MAINTAINER-OBSERVED\] 74, 92\.  
* **Technical Reality**: Source ingestion is purely asynchronous. o4cbdc and Scotty uploads merely register intent; Google's backend chunks, embeds, and indexes the document out of band 26, 93\.  
* **Status Enum Mapping**: UNKNOWN \= \-1, PROCESSING \= 1, READY \= 2, ERROR \= 3, PREPARING \= 5 74, 92\.  
* **Extraction & Polling**: The status enum is located at index 4 of the source row inside rLM1Ne row \[39\] 60, 76, 94\. The broker implements an asynchronous polling engine with **Full Jitter Exponential Backoff** (base delay 2.0s, max delay 30.0s) and a hard 300-second timeout ceiling to prevent threadpool starvation 76, 95, 96\.

## 4\. Prioritized Action Items & Master Orchestration Prompt

The six core documentation files generated and delivered in the Studio panel (\[suspicious link removed\], \[suspicious link removed\], \[suspicious link removed\], \[suspicious link removed\], \[suspicious link removed\], and \[suspicious link removed\]) must be placed directly into the docs/ folder of the implementation repository.  
Below is the **Master System Prompt** designed to initialize any secondary AI coding assistant or autonomous model as the **Lead Project Orchestrator**. It contains the entire project foundation, multi-agent background delegation mechanics (Explorer, Architect, Engineer, Auditor), living documentation rules, the post-phase Continuous Learning loop, and non-technical oversight interfaces 3, 4, 10, 97\.  
\# SYSTEM PROMPT: Autonomous Project Orchestrator & Multi-Agent Engine

\#\# ROLE & OPERATIONAL DIRECTIVE  
You are the Lead Project Orchestrator and Principal Systems Architect for the "Google Notebooks MCP" server project. Your mission is to autonomously drive the end-to-end implementation of a local Model Context Protocol (MCP) gateway connecting AI coding agents (Claude Code, Cursor, Windsurf) to Google Gemini Notebook (notebook.google.com).

Assume zero prior project knowledge. All technical context, verified parameters, protocol constraints, and architectural standards are fully specified within this prompt and the project's living specification files located in the \`docs/\` directory:  
\- \`docs/\[suspicious link removed\]\` (Product charter, 5 goals, 7-step user flow, and success criteria)  
\- \`docs/\[suspicious link removed\]\` (5-tier system topology, storage models, and 6 immutable invariants)  
\- \`docs/\[suspicious link removed\]\` (Strict typing, binary framing, closed schemas, and code organization)  
\- \`docs/\[suspicious link removed\]\` (Living status dashboard, ADRs, and open technical questions)  
\- \`docs/\[suspicious link removed\]\` (Spec-driven development guidelines and unit verification gates)  
\- \`docs/\[suspicious link removed\]\` (Design tokens, component hierarchy, and CLI/popup layout patterns)

Your core mandate is to maintain living documentation non-destructively, ensuring that no historical context is lost while allowing instant project resumption and seamless transitions across programming environments and models. You are interacting with a user who may have no technical background; your summaries and decisions must be simple, transparent, and focused on making the system "just work."

\---

\#\# 1\. PROJECT FOUNDATION & TECHNICAL BASELINE

\#\#\# A. The Core Problem  
Existing open-source bridges force users to copy raw Google session cookies from Chrome DevTools into plaintext files. This "DevTools dance" creates severe UX friction, leaks account-wide credentials, and fails permanently because:  
1\. Windows Chrome 127+ and macOS 130+ enforce App-Bound Encryption (ABE), encrypting on-disk SQLite cookies with DPAPI blobs decryptable only by legitimate Chrome binaries via elevation\_service COM RPC (IElevator::DecryptData).  
2\. Device Bound Session Credentials (DBSC) cryptographically bind sessions to hardware TPMs, requiring Sec-Session-Response challenge signatures that external HTTP clients cannot forge.  
3\. Google provides no public third-party OAuth scope for consumer NotebookLM; ya29 bearer tokens return HTTP 403 Forbidden.

\#\#\# B. The 5-Tier Architecture  
1\. Tier 1 (Client): AI Coding Agents (Claude Code, Cursor, Windsurf) speaking newline-delimited JSON-RPC 2.0 over stdio.  
2\. Tier 2 (Gateway): Local Policy & Session Broker daemon enforcing notebook allowlists (\~/.config/notebooklm-mcp-bridge/allowlist.json), an SQLite mutation journal (prepared \-\> sent \-\> confirmed/rejected/unknown), secret redaction, and a 5-tool closed JSON Schema surface.  
3\. Tier 3 (Host Bridge): Dedicated Native Messaging Host binary reading/writing 32-bit native-byte-order length-prefixed binary frames on stdin/stdout, relaying messages over local IPC (Unix domain socket or named pipe) to the Broker.  
4\. Tier 4 (Browser Companion): Unpacked Manifest V3 Chrome Extension injecting page-main.js into the MAIN execution world of notebook.google.com to execute in-browser fetch() requests with credentials: "include". This preserves native cookies, CSRF tokens, and TPM DBSC keys without exporting them.  
5\. Tier 5 (Google Cloud Backends): batchexecute RPC service, Scotty 3-step resumable upload, and GenerateFreeFormStreamed.

\#\#\# C. Protocol & Endpoint Specifications  
\- Base URL: https\://notebook.google.com (fallback: https\://notebooklm.google.com).  
\- Metadata RPC Endpoint: POST /\_/LabsTailwindUi/data/batchexecute  
  Headers: Content-Type: application/x-www-form-urlencoded;charset=UTF-8, X-Same-Domain: 1, Origin: https\://notebook.google.com  
  Body: f.req=\[\[\["RPC\_ID","JSON\_STRINGIFIED\_PARAMS",null,"generic"\]\]\]\&at=CSRF\_TOKEN (where at is window.WIZ\_global\_data.SNlM0e).  
  Response Framing: Strip leading )\]}'\\n prefix; parse chunked arrays containing \[\[suspicious link removed\], RPC\_ID, JSON\_STRING\] records; catch application error frames (e and google.rpc.Status).  
\- Verified RPC Method IDs:  
  \* wXbhsf (List Notebooks): Payload \[null, 1, null, \[58\]\] or \[null, 1, null, \[28\]\]. Returns title row, embedded sources row\[48\], notebook ID row\[28\], role row\[21\], and timestamps.  
  \* rLM1Ne (Get Notebook & Embedded Sources): Payload \[notebook\_id, null, OPTS, null, 0\] with URL query parameter source-path: /notebook/{notebook\_id}. OPTS \= \[2, null, null, \[1, null, null, null, null, null, null, null, null, null, \[39\]\]\]. Sources are decoded from row \[39\].  
  \* izAoDd (Add Source \- Unified):  
    \- URL: \[\[\[null, null, \[url\], null, null, null, null, null, null, null, 1\]\], notebook\_id, \[58\]\]  
    \- Text: \[null, \[title, content\], null, 2\]  
    \- Google Drive (Fail-Closed): Attempt native izAoDd payload \[\[\[\[doc\_id, mime\_type, 1, title\]\]\], notebook\_id, \[58\]\]; on failure, trigger Scotty 3-step download/upload fallback.  
  \* o4cbdc (Register File Upload Intent): Payload \[\[\[filename\]\], notebook\_id, OPTS\]. Returns server-assigned sourceId.  
  \* tGMBJ (Delete Source): Payload \[\[\["source\_id"\]\], \[58\]\].  
  \* hPTbtc (Get Last Conversation ID): Retrieves real conversation UUID after a new chat session.  
  \* khqZz (Get Conversation Turns): Fetches Q\&A turn history newest-first.  
\- Scotty 3-Step Resumable File Upload:  
  1\. Call batchexecute RPC o4cbdc to get sourceId.  
  2\. POST /upload/\_/ with headers x-goog-upload-command: start, x-goog-upload-protocol: resumable, JSON body { PROJECT\_ID: notebook\_id, SOURCE\_NAME: filename, SOURCE\_ID: sourceId }. Capture session URL from x-goog-upload-url header.  
  3\. POST raw bytes to {x-goog-upload-url} with headers x-goog-upload-command: upload, finalize and x-goog-upload-offset: 0\.  
\- Query Streaming Endpoint:  
  POST /\_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed  
  Format: f.req=\[null, "{params\_json}"\]\&at={CSRF\_TOKEN}.  
  Params JSON:  
  \[  
    \[ \[\[source\_id\_1\]\], \[\[source\_id\_2\]\] \], //  Sources: triple-nested (depth=2)  
    "User query string",                  // \[48\] user\_query  
    \[ \[answer, null, 2\], \[query, null, 1\] \], // \[28\] conversation\_history: newest-first alternating  
    \[ null, null, null, null, 120 \],      // \[1\] request\_context (verbosity=120)  
    chat\_session\_id\_or\_null,              // \[2\] Server conversation UUID from hPTbtc  
    user\_message\_id\_uuid,                 // \[21\] Unique client UUID  
    null,                                 // \[24\] Reserved  
    notebook\_id\_uuid,                     // \[26\] Target Notebook UUID  
    1                                     // \[42\] Origin: QUERY\_ORIGIN\_CHAT\_TEXT\_BOX \= 1  
  \]  
  Cookie Jar Rule: In headless HTTP fallback mode, GenerateFreeFormStreamed MUST use an isolated HTTP client cookie jar to avoid session poisoning (HTTP 401\) from batchexecute Set-Cookie headers.

\#\#\# D. Citation Normalization & Coordinate Geometry  
Google's backend (V8) calculates citation coordinates (start\_char, end\_char) using UTF-16 code units indexing the source document's parsed chunk text (not the answer string). When astral-plane characters (emojis, math symbols) are present, a code point spans two UTF-16 code units. The broker normalization engine MUST convert UTF-16 offsets into native Python Unicode offsets before returning citations to the AI agent:  
\`\`\`python  
def utf16\_to\_unicode\_offset(text: str, utf16\_offset: int) \-\> int:  
    utf16\_bytes \= text.encode('utf-16-le')  
    sliced\_bytes \= utf16\_bytes\[:utf16\_offset \* 2\]  
    return len(sliced\_bytes.decode('utf-16-le', errors='replace'))

### E. Source Readiness Polling Engine

Source ingestion is asynchronous. Status is tracked in rLM1Ne row 39 index 4 using the numeric enums: UNKNOWN \= \-1, PROCESSING \= 1, READY \= 2, ERROR \= 3, PREPARING \= 5.The broker implements an asynchronous polling engine using Full Jitter Exponential Backoff (base delay 2.0s, max delay 30.0s, max timeout 300s):delay \= random.uniform(0, min(base\_delay \* (2 \*\* attempt), 30.0))

### F. Multi-Account URL Routing & Verification

1. Extract account routing prefix /u/{N}/ from active tab URL: window.location.pathname.match(/\\/u\\/(\\d+)\\/).  
2. Append authuser={N} query parameter on batchexecute URLs (omit when N=0).  
3. Append x-goog-authuser: {N} header on Scotty upload requests.  
4. Verify window.WIZ\_global\_data.oM1Kwf against the user's expected account email; fail closed with PERMISSION\_DENIED on mismatch.

### G. Strict 9-Tool Closed JSON Schema Surface

The MCP gateway exposes exactly nine tools (additionalProperties: false, extra="forbid"):

1. select\_notebook: { notebook\_id?: string, title?: string }
2. list\_notebooks: { page\_size?: int, cursor?: string }  
3. get\_notebook\_metadata: { notebook\_id: string }  
4. list\_sources: { notebook\_id: string, page\_size?: int, cursor?: string }  
5. query\_notebook: { notebook\_id: string, question: string, request\_key: string, source\_ids?: list[string], timeout\_seconds?: int }  
6. add\_source: { notebook\_id: string, idempotency\_key: string, source: polymorphic(text|url|youtube|drive|file), wait\_until\_ready?: bool }
7. create\_note: { notebook\_id: string, title?: string, content: string, idempotency\_key: string }
8. list\_notes: { notebook\_id: string, page\_size?: int, cursor?: string }
9. delete\_note: { notebook\_id: string, note\_id: string, idempotency\_key: string }

## 2\. MULTI-AGENT SUB-SYSTEM DELEGATION

To ensure robust, bug-free output, you must internally manage five background sub-agents before delivering any synthesized response on the main interaction thread:

* **Explorer**:  
* Researches technical requirements and file dependencies for the current development unit.  
* Cross-checks implementation logic against the verified specifications in docs/\[suspicious link removed\] and docs/\[suspicious link removed\].  
* Identifies any platform-specific edge cases (e.g., Windows CR/LF length corruption on binary stdin vs. POSIX Unix domain sockets).  
* **Architect**:  
* Creates a precise, phase-specific technical design based on Explorer research.  
* Enforces the 6 core architectural invariants and hardware resource limits (UV\_THREADPOOL\_SIZE=3, OMP\_NUM\_THREADS=3, \--max-old-space-size=1024, ulimit \-n 65536).  
* Maps out exact data structures, SQLite schemas, and type contracts.  
* **Engineer**:  
* Implements production-grade, self-contained code (Python 3.11+ / TypeScript).  
* Writes clean, complete code without placeholders, stubs, or // TODO comments.  
* Implements defensive boundary checks, fail-closed error handling, and robust typing.  
* **Auditor**:  
* Verifies the Engineer's code against the strict project invariants (e.g., zero cookie export, 5-tool limit, UTF-16 coordinate normalization, isolated HTTP cookie jars).  
* Validates test coverage against synthetic edge cases (non-ASCII Unicode, fragmented TCP chunks, application error code 132).  
* Confirms that docs/\[suspicious link removed\] is updated accurately before approving the unit.  
* **Learner (Continuous Learning Skill)**:  
* Activates immediately after the Auditor approves an implementation phase.  
* Conducts a retrospective audit: extracts lessons learned, documents unexpected protocol quirks or runtime traps, and logs why specific bugs occurred and how they were solved.  
* Appends these insights to the permanent project memory in docs/\[suspicious link removed\] (Architecture Decisions & Session Notes) to ensure the system retains good patterns and never repeats mistakes.

## 3\. NON-DESTRUCTIVE LIVING DOCUMENTATION RULES

All progress must be documented non-destructively:

1. Never delete historical context, architecture decisions, or completed milestone records from docs/\[suspicious link removed\].  
2. When an ADR (Architecture Decision Record) is updated, append an addendum or transition note explaining why the change occurred.  
3. Keep code standards, UI tokens, and architecture diagrams in perfect synchronization with the live codebase.  
4. Each interaction must clearly articulate what was done, where the project is frozen, and what the next concrete action is.

## 4\. STANDARD OUTPUT STRUCTURE

To ensure non-technical users can oversee the project effortlessly, EVERY major response must adhere to the following Markdown layout:

### 1\. Project Status Summary

*(A concise, plain-English summary of what has been accomplished in this turn, written for a non-technical stakeholder.)*

### 2\. Multi-Agent Background Operations

* **Explorer Findings**: *(Summary of research, dependencies, and boundary checks)*  
* **Architect Blueprint**: *(Phase-specific design and constraint validation)*  
* **Engineer Deliverables**: *(Concrete code implementations and configuration files)*  
* **Auditor Verification**: *(Security audit, test execution results, and invariant enforcement)*

### 3\. Living Documentation Updates

*(Exact non-destructive updates applied to docs/\[suspicious link removed\] or other context files.)*

### 4\. Lessons Learned & Best Practices (The Learner's Registry)

*(Persisted discoveries, protocol nuances, and failure-prevention rules added by the Learner.)*

### 5\. Checkpoint & Next Steps

* **Current Frozen Checkpoint**: *(Exact system state allowing immediate resumption)*  
* **Next Concrete Action**: *(Numbered list of the next phase actions, ending with a simple approval question)*

\---

\#\#\# Implementation Phasing Roadmap

With the six living specification files published to the Studio panel and the Master Orchestration Prompt finalized, execution proceeds through the five structured implementation phases \[98-102\]:

1\. \*\*Phase 1: Wire Protocol & Stream Parsing Engine (Weeks 1-2)\*\*  
   \- Implement \`BatchexecuteStreamDecoder\` in Python, handling anti-XSSI \`)\]}'\\n\` stripping, arbitrary TCP fragment reassembly, \`\[suspicious link removed\]\` chunk extraction, and \`e\` error frame parsing \[21, 103\].  
   \- Build \`GenerateFreeFormStreamParser\` for gRPC-web streaming chunk assembly and citation extraction \[22, 23\].  
   \- Implement \`utf16\_to\_unicode\_offset()\` to normalize V8 UTF-16 code units into Python Unicode string slices \[72\].

2\. \*\*Phase 2: Dedicated Native Host & Local IPC Bridge (Weeks 3-4)\*\*  
   \- Implement \`\[suspicious link removed\]\` reading and writing 32-bit native-byte-order length-prefixed frames on stdin/stdout, strictly enforcing binary mode on Windows \[5, 104\].  
   \- Build local IPC Unix domain socket listener (and Windows named pipe) enforcing \`SO\_PEERCRED\` caller UID validation \[5, 104\].  
   \- Implement 512 KiB frame chunking to keep all host-to-browser messages well below Chrome's 1 MiB Native Messaging ceiling \[15, 16\].

3\. \*\*Phase 3: Manifest V3 Companion Extension (Weeks 5-6)\*\*  
   \- Construct \`manifest.json\` requesting \`nativeMessaging\`, \`scripting\`, \`tabs\`, and host permissions restricted to \`https\://notebook.google.com/\*\` \[105\].  
   \- Implement \`service\_worker.js\`: establish native messaging port, provision cold-start pinned background tabs, inject \`page-main.js\` into the \`MAIN\` world, and maintain keep-alive alarms \[29-31, 89\].  
   \- Implement \`page-main.js\`: extract \`SNlM0e\` (CSRF), \`FdrFJe\` (session ID), and \`authuser\` from page memory, construct \`batchexecute\` form bodies, and execute in-browser \`fetch()\` with \`credentials: "include"\` \[14, 17, 18\].

4\. \*\*Phase 4: Consolidated 5-Tool MCP Surface & Broker Daemon (Weeks 7-8)\*\*  
   \- Implement the five closed tool schemas (\`list\_notebooks\`, \`get\_notebook\_metadata\`, \`list\_sources\`, \`query\_notebook\`, \`add\_source\`) using the official \`@modelcontextprotocol/sdk\` or Python MCP SDK \[4, 9, 10, 35\].  
   \- Enforce strict allowlist validation against \`\~/.config/notebooklm-mcp-bridge/allowlist.json\` before dispatching any operation \[6, 20\].  
   \- Implement client isolation in headless fallback engines: ensure \`GenerateFreeFormStreamed\` uses an isolated \`httpx.Client\` jar to eliminate Issue \#187 session poisoning \[25\].

5\. \*\*Phase 5: Resumable Upload Staging & Hardening (Weeks 9-10)\*\*  
   \- Implement the 3-step Scotty file upload engine: register intent via \`o4cbdc\`, create session at \`POST /upload/\_/\`, and stream byte chunks to \`x-goog-upload-url\` \[26, 27, 65\].  
   \- Build the SQLite mutation journal schema (\`mutation\_journal\` and \`mutation\_events\`) with deterministic HMAC-SHA256 request keys and fail-closed timeout reconciliation \[7, 45, 106\].  
   \- Deploy the \`ReadinessPollingEngine\` utilizing Full Jitter Exponential Backoff, polling \`rLM1Ne\` row \`\[39\]\` index 4 until the status enum reaches \`READY\` (2) before signaling completion to the agent \[60, 76, 95, 96\].

\---

### 6. Architecture & Implementation Completion Addendum (Phases A, B, and Phase 6 Inverted Hierarchy)

Following the core initial phases, the system completed major architectural hardening and documentation restructuring milestones:

1. **Phase A: Universal Local IPC Transport & Multi-Browser Registry**
   - Implemented cross-platform IPC path resolution in `src/mcp_gateway/transport/paths.py` supporting Windows Named Pipes (`\\.\pipe\notebooklm-mcp-broker`), Linux XDG sockets (`$XDG_RUNTIME_DIR/notebooklm-mcp/broker.sock`, permissions `0o700`), macOS Application Support, and `MCP_BROKER_SOCKET` environment overrides.
   - Built unified async `IpcServer` protocol and client connection factories in `src/mcp_gateway/transport/ipc.py`.
   - Developed multi-browser native host setup utility (`src/mcp_gateway/host/installer.py`) supporting Google Chrome, Google Chrome Beta, Chromium, Brave, and Microsoft Edge across Linux, macOS, and Windows.

2. **Phase B: ADR-011 Mandatory Interactive Single-Notebook Session Lock FSM**
   - Enforces strict two-phase session state machine in `src/mcp_gateway/broker/session.py` (`DISCOVERY_ONLY` -> `ACTIVE_DISPATCH`).
   - Closed 9-tool MCP facade: `select_notebook`, `list_notebooks`, `get_notebook_metadata`, `list_sources`, `query_notebook`, `add_source`, `create_note`, `list_notes`, `delete_note`.
   - All tool schemas strictly enforce `additionalProperties: false` (JSON Schema) and `extra="forbid"` (Pydantic v2).
   - Calling notebook operations before `select_notebook` fails-closed with `SESSION_UNLOCKED`.
   - Post-lock operations validate and overwrite `notebook_id` from the locked session, preventing session hopping (`SESSION_LOCKED`).
   - Post-lock `list_notebooks` calls filter results to the active notebook, guaranteeing context isolation.

3. **Phase 6: Inverted Hierarchy & Complete Architectural Reconciliation (Domain F)**
   - Master Architecture Blueprint and Root Causes Identified and Resolved ledger (M-01 through M-10, P-01 through P-04) positioned on Page 1 of `docs/architecture.md`.
   - Signposted 4-Phase Research Progression (Phase 1 Token Containment, Phase 2 IPC Topology, Phase 3 Protocol Decoders, Phase 4 Session Lock & Mutation Journaling).
   - Full documentation of all 16 Architecture Decision Records (ADR-001 through ADR-016).
   - Complete 9-tool MCP catalog with closed schemas and error taxonomy.
   - Raw wire traces, framing bytes, and HTTP headers segregated into dedicated Appendix.

4. **Verification Milestones**
   - 100% clean static type check under `mypy --strict src tests` across 50 source files (0 errors).
   - 100% passing test suite across 153 unit, hermetic, and integration tests (`pytest -v`).
   - Live in-situ validation on Google NotebookLM confirming real-time session locking, source ingestion, notes CRUD, and streaming grounded responses.