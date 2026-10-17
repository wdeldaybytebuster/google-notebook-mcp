# Security Policy

## Supported Versions

We provide security updates and patches for the following versions:

| Version | Supported          |
| :------ | :----------------- |
| `0.1.x` | :white_check_mark: |

---

## Reporting a Vulnerability

The **Google Notebook MCP Gateway** operates within sensitive security boundaries, specifically interfacing between local AI processes and private Google NotebookLM knowledge bases without credential export.

If you believe you have found a security vulnerability (such as a credential leak, bypass of the secret scrubber, arbitrary code execution via native messaging, or a flaw in mutation journaling):

1. **Do NOT open a public GitHub issue.**
2. Report the vulnerability privately via **[GitHub Private Vulnerability Reporting](https://github.com/wdeldaybytebuster/google-notebook-mcp/security/advisories/new)**.
3. If private reporting is unavailable, email the maintainer securely at **wdeldaybytebuster@users.noreply.github.com** with the subject line `[SECURITY] Google Notebook MCP Vulnerability`.

### Please Include:
- A detailed description of the vulnerability.
- Proof of Concept (PoC) code or steps to reproduce.
- Any relevant logs (with personal credentials redacted).
- Impact assessment.

### Our Commitment:
- We will acknowledge receipt of your vulnerability report within **48 hours**.
- We will provide an estimated timeline for remediation and keep you updated on progress.
- We will credit you in the security advisory once the patch is published (unless you prefer anonymity).
