---
name: adversarial-consultation-planner
description: Executes closed-loop grounded consultations with live models/systems using tripartite brainstorming, adversarial red-team auditing, and remediation invariant synthesis before planning or implementation.
---

# Adversarial Consultation Planner

Unvetted plans build vulnerable systems. Always ground, stress-test adversarially, and extract invariants before touching code.

## When to Use

- When planning major architectural upgrades, new protocol standardizations, or complex integrations.
- When interfacing with undocumented, private, or evolving upstream SaaS APIs (e.g., Google NotebookLM, internal microservices).
- When designing systems on resource-constrained edge hardware (e.g., Chromebook i3-N305, 6.4 GB RAM, zero swap) where memory spikes or unhandled loops cause OS eviction.
- Before writing any multi-phase implementation plan that requires formal stakeholder, user, or client model clearance.

## When NOT to Use

- For trivial one-line bug fixes or typo corrections.
- For well-defined, static tasks with zero architectural ambiguity.

---

## The Process

### Step 1: Reconnaissance & Repository Grounding
Before querying or proposing solutions:
1. Map existing runtime constraints, active schemas, and hardware bounds.
2. Verify communication transport (e.g. Unix domain socket, stdio IPC, Chrome Native Messaging).
3. Confirm session lock and target dataset/notebook identity (ADR-011).

### Step 2: Positive Gap Analysis (Round 1 Consultation)
Formulate a focused, bite-sized inquiry exploring:
- Desired capabilities and protocol standards.
- Candidate topology and component decoupling.
- Edge hardware requirements.
- *Query Rule:* Avoid monolithic 5-topic prompts. Slice queries into bite-sized questions (60–120s execution ceiling) to prevent browser service worker timeouts (240s kill wall).

### Step 3: Adversarial Red-Team Stress-Testing (Round 2 Consultation)
Subject the Round 1 proposal to an aggressive, antagonistic critique:
- **Resource Exhaustion**: How will high-bandwidth binary data, Base64 strings, or large collections affect host RAM and earlyoom daemons?
- **Transport & Timeout Severance**: What happens if the connection breaks mid-stream, the upstream worker idles out, or tabs are discarded?
- **Schema & Array Drift**: What happens if the upstream service shifts internal tuple positions, array offsets, or UI element selectors?
- **Security & Privilege Escalation**: Can malicious input, cross-notebook requests, or prompt injections bypass session locks or allowlists?
- **Loop & Quota Depletion**: Can retry logic or recursive tool dispatch enter an infinite loop?

### Step 4: Extraction of Non-Negotiable Remediation Invariants
Translate every vulnerability identified in the adversarial audit into a strict, numbered Invariant:
- Invariants must specify the exact data structure, memory buffer, byte ceiling, or assertion canary.
- Invariants must be non-negotiable prerequisites before implementation code is written.

### Step 5: Implementation Plan Assembly & Final Clearance Loop
1. Incorporate all remediation invariants into a formal `implementation_plan.md`.
2. Structure work into discrete, verifiable phases with clear acceptance criteria.
3. Submit the comprehensive plan back to the consultation partner for formal audit verification.
4. Obtain final user/stakeholder approval before modifying codebase files.

---

## Key Principles & Guardrails

- **Single-Topic Query Slicing**: When consulting living models across large knowledge bases (100+ sources), always slice questions into single-domain inquiries to stay within 240s RPC timeouts.
- **Fail-Closed loud canaries (M-05)**: Never use permissive fallbacks or silent defaults for upstream schema drift. Assert tuple lengths and raise `UPSTREAM_SCHEMA_DRIFT` immediately.
- **Zero Memory Tmpfs Slicing**: Stream binary data directly to disk/tmpfs in $\le 512\text{ KiB}$ slices rather than buffering in memory or JSON-RPC text.
- **Air-Gapped Personal Config Isolation**: Separate auto-updating adapter schemas from user personal settings (`allowlist.json`, `.notebook_mcp.json`). Updates must never overwrite user state.
- **Circuit Breakers**: Cap agent tool dispatch depth to 10 calls per task sequence, 3 retries max with Full Jitter backoff, and 320 MB memory reserve buffer.
