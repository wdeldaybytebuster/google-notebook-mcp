---
name: adversarial-consultation-planner
description: Use before creating plans or modifying code for complex or undocumented systems to conduct closed-loop consultations with live models, adversarial stress-testing, and remediation invariant synthesis.
allowed-tools:
- query_notebook
- list_sources
- select_notebook
metadata:
  category: Architecture & Strategy
  tags:
  - consultation-planning
  - adversarial-audit
  - red-teaming
  - invariant-synthesis
  - closed-loop
---

# Adversarial Consultation Planner

Unvetted plans build vulnerable systems. Always ground, stress-test adversarially, and synthesize non-negotiable remediation invariants before touching code.

---

## When to Use

- When planning major architectural upgrades, new protocol standardizations, or complex feature additions.
- When interfacing with undocumented, private, or dynamically evolving upstream services (e.g. Google NotebookLM, internal microservices).
- When designing systems for resource-constrained edge hardware (e.g., Chromebook i3-N305, 6.4 GB RAM, zero swap) where memory spikes or unhandled loops cause OS eviction.
- Before writing any multi-phase implementation plan that requires formal stakeholder, user, or model clearance.

## When NOT to Use

- For trivial one-line bug fixes or typo corrections.
- For well-defined, static tasks with zero architectural or operational ambiguity.
- For purely exploratory conversations where no implementation plan is being constructed.

---

## The Process

```
[Reconnaissance] ──→ [Round 1: Gap Analysis] ──→ [Round 2: Adversarial Red-Team] ──→ [Invariant Synthesis] ──→ [Formal Clearance]
```

### Step 1: Reconnaissance & Baseline Decoupling
1. **Map Constraints:** Inspect target hardware profiles, memory caps (`NODE_OPTIONS`, `UV_THREADPOOL_SIZE`), process niceness, and transport layers.
2. **Decouple Spec vs Plan (Section XI Invariant):**
   - Identify the baseline specification title (`SPEC_SOURCE_TITLE`).
   - Identify the candidate proposal title (`CANDIDATE_PLAN_TITLE`).
   - **Never** prompt the model to compare a baseline specification against itself.

### Step 2: Positive Gap Analysis (Round 1 Consultation)
Formulate a focused, single-domain inquiry dispatched via `query_notebook`:
- Desired capabilities and protocol standards.
- Component decoupling and boundary contracts.
- Edge hardware memory ceilings ($\le 512\text{ KiB}$ IPC chunking, 320 MB safety buffer).
- *Single-Topic Query Slicing:* Slice inquiries into bite-sized questions (45–90s duration) to prevent browser service worker timeouts (240s kill wall).

### Step 3: Adversarial Red-Team Stress-Testing (Round 2 Consultation)
Subject the Round 1 proposal to an antagonistic critique across five core failure domains:
1. **Resource Exhaustion & OOM:** How will high-bandwidth binary streams or Base64 payloads affect RAM and `earlyoom`?
2. **Transport & Timeout Severance:** What happens on abrupt socket severance, tab discard, or MV3 30-second idle?
3. **Upstream Schema Drift:** How will the engine detect and respond to unannounced Google array index shifts?
4. **Security & Privilege Escalation:** Can malicious input, cross-notebook requests, or prompt injections bypass session locks?
5. **Infinite Loops & Quota Depletion:** Can retry logic or recursive tool dispatch enter an unbounded loop?

### Step 4: Remediation Invariant Synthesis
Translate every vulnerability identified in the adversarial audit into a strict, numbered Invariant:
- Invariants must specify exact data structures, memory buffers, byte ceilings, or loud assertion canaries.
- Invariants must be non-negotiable prerequisites before implementation code is written.

### Step 5: Implementation Plan Assembly & Final Clearance Loop
1. Incorporate all remediation invariants into a formal `implementation_plan.md`.
2. Structure work into discrete, bite-sized phases with explicit acceptance criteria.
3. Submit the comprehensive plan back to the consultation model for final audit verification:
   - Require explicit formal verdict: `VERDICT: APPROVED WITH ADVERSARIAL INVARIANTS INCLUDED`.
4. Obtain final user/stakeholder approval before modifying codebase files.

---

## Agent Anti-Patterns & Rationalizations (What to Avoid)

| Rationalization (DO NOT DO) | Correction |
| :--- | :--- |
| *"The plan looks simple and straightforward, so I will skip the adversarial red-team phase."* | **FORBIDDEN.** Complex edge failure modes (such as MV3 timeouts, buffer overflows, and schema drift) are caught specifically during the adversarial stress-test. |
| *"I'll send a 5,000-word prompt covering everything at once."* | **FORBIDDEN.** Monolithic prompts exceed browser execution bounds and cause timeouts. Slice into targeted, bite-sized inquiries. |
| *"I will prompt the model to compare the specification against itself."* | **FORBIDDEN.** Strictly decouple `SPEC_SOURCE_TITLE` from `CANDIDATE_PLAN_TITLE`. |
| *"I'll start coding before the consultation model returns formal approval."* | **FORBIDDEN.** Follow the gated sub-agent dev cycle: Research $\rightarrow$ Verify $\rightarrow$ Blueprint $\rightarrow$ Code $\rightarrow$ Audit. |

---

## Verification Checklist

Before presenting an implementation plan for approval:

- [ ] Baseline specification decoupled from candidate plan.
- [ ] Round 1 Gap Analysis executed with single-topic query slicing.
- [ ] Round 2 Adversarial Stress-Test executed covering the 5 failure domains.
- [ ] Non-negotiable remediation invariants synthesized and numbered.
- [ ] Invariants incorporated directly into `implementation_plan.md`.
- [ ] Formal clearance verdict obtained from consultation partner.
- [ ] Final plan presented to user with explicit Phase stop gates.
