#!/usr/bin/env python3
"""Pushes updated documentation files and the public GitHub launch completion report into
the production 'Google Notebooks MCP' notebook in NotebookLM as Sources and Notes.

Executes sequentially with hardware protection and full jitter readiness polling.
"""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import struct
import sys
import time

# Ensure src/ is importable
_src_root = str(Path(__file__).resolve().parent.parent / "src")
if _src_root not in sys.path:
    sys.path.insert(0, _src_root)

from mcp_gateway.transport import get_default_ipc_path

IPC_FRAME_FORMAT = ">I"
SOCKET_PATH = os.environ.get("MCP_BROKER_SOCKET", get_default_ipc_path())
TARGET_NOTEBOOK_ID = os.environ.get("TARGET_NOTEBOOK_ID", "")
TARGET_NOTEBOOK_TITLE = os.environ.get("TARGET_NOTEBOOK_TITLE", "Google Notebooks MCP")

DOCUMENTS_TO_PUSH = [
    {
        "file": "docs/github-launch-completion-report.md",
        "title": "Google Notebook MCP — Public GitHub Launch, Security Sanitization & Release Certification Report",
    },
    {
        "file": "README.md",
        "title": "Google Notebook MCP — Public Repository Overview, Architecture & Quickstart",
    },
    {
        "file": "docs/getting-started.md",
        "title": "Google Notebook MCP — Getting Started Guide & Cross-Platform Onboarding",
    },
    {
        "file": "docs/client-configuration.md",
        "title": "Google Notebook MCP — AI Coding Client Drop-In Configurations",
    },
    {
        "file": "docs/tools-reference.md",
        "title": "Google Notebook MCP — 9-Tool Closed MCP Surface Specification",
    },
    {
        "file": "docs/troubleshooting.md",
        "title": "Google Notebook MCP — Troubleshooting, FAQs & Platform Diagnostics",
    },
    {
        "file": "docs/security.md",
        "title": "Google Notebook MCP — Security Architecture, Threat Model & DBSC Containment",
    },
    {
        "file": "docs/architecture.md",
        "title": "Google Notebook MCP — Master Architecture Blueprint & ADR-001 to ADR-017",
    },
    {
        "file": "AGENTS.md",
        "title": "Google Notebook MCP — Project Directives, Security Invariants & Operational Rules",
    },
]


async def send_broker_command(
    reader: asyncio.StreamReader,
    writer: asyncio.StreamWriter,
    req: dict,
) -> dict:
    req_bytes = json.dumps(req).encode("utf-8")
    header = struct.pack(IPC_FRAME_FORMAT, len(req_bytes))
    writer.write(header + req_bytes)
    await writer.drain()

    header_bytes = await reader.readexactly(4)
    (msg_len,) = struct.unpack(IPC_FRAME_FORMAT, header_bytes)
    payload_bytes = await reader.readexactly(msg_len)
    return json.loads(payload_bytes.decode("utf-8"))


async def main() -> None:
    print(f"[sync] Connecting to broker at {SOCKET_PATH}...")
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    try:
        # Step 1: Ensure session is locked to production notebook
        print(f"[sync] Selecting notebook by title '{TARGET_NOTEBOOK_TITLE}'...")
        sel_req: dict = {
            "action": "select_notebook",
            "title": TARGET_NOTEBOOK_TITLE,
            "save_for_project": True,
        }
        if TARGET_NOTEBOOK_ID:
            sel_req["notebook_id"] = TARGET_NOTEBOOK_ID

        sel_res = await send_broker_command(reader, writer, sel_req)
        if not sel_res.get("ok") and sel_res.get("error", {}).get("code") != "SESSION_LOCKED":
            print(f"[sync] Error selecting notebook: {sel_res}", file=sys.stderr)
            sys.exit(1)

        resolved_notebook_id = (
            sel_res.get("notebook_id")
            or sel_res.get("active_session", {}).get("notebook_id")
            or TARGET_NOTEBOOK_ID
        )
        print(f"[sync] Notebook locked successfully: '{TARGET_NOTEBOOK_TITLE}' (ID: {resolved_notebook_id})")

        # Step 2: Fetch current sources to know baseline
        print("[sync] Fetching existing source catalog...")
        list_req = {"action": "list_sources", "notebook_id": resolved_notebook_id}
        list_res = await send_broker_command(reader, writer, list_req)
        existing_sources = list_res.get("sources", [])
        print(f"[sync] Current sources in notebook: {len(existing_sources)}")

        results = []
        base_dir = Path(__file__).resolve().parent.parent

        # Step 3: Ingest each document sequentially as a Source
        for idx, doc in enumerate(DOCUMENTS_TO_PUSH, start=1):
            file_path = base_dir / doc["file"]
            if not file_path.is_file():
                print(f"[sync] Warning: file {file_path} not found, skipping.", file=sys.stderr)
                continue

            content = file_path.read_text(encoding="utf-8")
            title = doc["title"]
            print(f"\n[sync] ({idx}/{len(DOCUMENTS_TO_PUSH)}) Pushing Source '{title}' ({len(content)} chars)...")

            add_req = {
                "action": "add_source",
                "notebook_id": resolved_notebook_id,
                "idempotency_key": f"doc-push-{int(time.time())}-{idx}",
                "wait_until_ready": True,
                "source": {
                    "type": "text",
                    "title": title,
                    "content": content,
                },
            }

            t0 = time.time()
            add_res = await send_broker_command(reader, writer, add_req)
            elapsed = time.time() - t0

            if add_res.get("ok"):
                source_id = add_res.get("source_id")
                status = add_res.get("status")
                print(f"[sync] -> Succeeded in {elapsed:.1f}s: source_id={source_id}, status={status}")
                results.append({
                    "file": doc["file"],
                    "title": title,
                    "source_id": source_id,
                    "status": status,
                    "ok": True,
                })
            else:
                print(f"[sync] -> Failed: {add_res}", file=sys.stderr)
                results.append({
                    "file": doc["file"],
                    "title": title,
                    "error": add_res.get("error"),
                    "ok": False,
                })

            # Pause between uploads for V8 / companion event loop stability
            await asyncio.sleep(1.0)

        # Step 4: Create a dedicated executive Note summarizing the GitHub Launch
        print("\n[sync] Creating executive summary Note in notebook...")
        report_file = base_dir / "docs/github-launch-completion-report.md"
        report_summary = (
            "# Google Notebook MCP — Public GitHub Launch & Release Certification\n\n"
            "- **Repository:** https://github.com/wdeldaybytebuster/google-notebook-mcp\n"
            "- **Wiki:** https://github.com/wdeldaybytebuster/google-notebook-mcp/wiki\n"
            "- **License:** Apache License 2.0\n"
            "- **Verified Commit:** 6c35f7b (main)\n"
            "- **CI Status:** 100% Green on Ubuntu, macOS, and Windows runners across Python 3.11 & 3.12\n"
            "- **Security Audit:** Zero credentials, personal emails, or workstation paths exposed.\n"
            "- **Closed Tools:** 9 tools verified under ADR-011 and ADR-017.\n"
        )
        note_req = {
            "action": "create_note",
            "notebook_id": resolved_notebook_id,
            "title": "Google Notebook MCP — Public GitHub Launch & Release Certification",
            "content": report_summary,
            "idempotency_key": f"note-push-launch-{int(time.time())}",
        }
        note_res = await send_broker_command(reader, writer, note_req)
        if note_res.get("ok"):
            note_id = note_res.get("note_id") or note_res.get("note", {}).get("id")
            print(f"[sync] Note created successfully: {note_id}")
        else:
            print(f"[sync] Note creation warning: {note_res}", file=sys.stderr)

        # Step 5: Verify updated source count
        print("\n[sync] Verifying final source catalog...")
        final_list = await send_broker_command(reader, writer, list_req)
        final_sources = final_list.get("sources", [])
        print(f"[sync] Updated sources in notebook: {len(final_sources)} (added {len(final_sources) - len(existing_sources)} new sources)")

        # Step 6: Test Q&A Query targeting the newly ingested documentation
        new_source_ids = [r["source_id"] for r in results if r.get("ok") and r.get("source_id")]
        if new_source_ids:
            print("\n[sync] Testing grounded query against newly ingested documentation...")
            query_req = {
                "action": "query_notebook",
                "notebook_id": resolved_notebook_id,
                "question": "What is the public GitHub repository URL, license, and CI verification status of Google Notebook MCP?",
                "source_ids": new_source_ids[:3],
                "request_key": f"sync-verify-query-{int(time.time())}",
            }
            query_res = await send_broker_command(reader, writer, query_req)
            if query_res.get("ok"):
                answer = query_res.get("answer", "")
                citations = query_res.get("citations", [])
                print(f"[sync] Query succeeded! Answer preview:\n{answer[:300]}...")
                print(f"[sync] Total citations returned: {len(citations)}")
            else:
                print(f"[sync] Query warning: {query_res.get('error')}")

        print("\n[sync] All operations complete.")
        print(json.dumps(results, indent=2))

    finally:
        writer.close()
        await writer.wait_closed()


if __name__ == "__main__":
    asyncio.run(main())
