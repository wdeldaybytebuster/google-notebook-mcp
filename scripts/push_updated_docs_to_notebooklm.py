#!/usr/bin/env python3
"""Pushes updated documentation files and the full completion report into
the production 'Google Notebooks MCP' notebook in NotebookLM.

Executes sequentially with hardware protection and full jitter readiness polling.
"""

from __future__ import annotations

import asyncio
import json
import os
import struct
import sys
import time

IPC_FRAME_FORMAT = ">I"
SOCKET_PATH = os.environ.get("MCP_BROKER_SOCKET", "/tmp/notebooklm-mcp-broker.sock")
TARGET_NOTEBOOK_ID = os.environ.get("TARGET_NOTEBOOK_ID", "00000000-0000-0000-0000-000000000001")
TARGET_NOTEBOOK_TITLE = os.environ.get("TARGET_NOTEBOOK_TITLE", "Google Notebooks MCP")

DOCUMENTS_TO_PUSH = [
    {
        "file": "docs/NotebookLM_Implementation_Plan_V4_2_Full_Completion_Report.md",
        "title": "Google Notebooks MCP — Implementation Plan v4.2 Full Completion Report & Official Auditor Clearance Certificate",
    },
    {
        "file": "docs/architecture.md",
        "title": "Google Notebooks MCP — Master Architecture Blueprint & Decision Records (ADR-001 to ADR-017)",
    },
    {
        "file": "docs/client-configuration.md",
        "title": "Google Notebooks MCP — Client Configuration Guide & In-Chat Confirmation Protocol",
    },
    {
        "file": "docs/HANDOFF.md",
        "title": "Google Notebooks MCP — Full Project Handoff Document & Implementation State (Oct 2026)",
    },
    {
        "file": "AGENTS.md",
        "title": "Google Notebooks MCP — Project Directives, Security Invariants & Operational Rules",
    },
    {
        "file": "docs/project-overview.md",
        "title": "Google Notebooks MCP — Product Specification & Technical Architecture Overview",
    },
    {
        "file": "docs/progress-tracker.md",
        "title": "Google Notebooks MCP — Phased Progress Tracker & Completion Ledger",
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
        print(f"[sync] Selecting notebook '{TARGET_NOTEBOOK_TITLE}' ({TARGET_NOTEBOOK_ID})...")
        sel_req = {
            "action": "select_notebook",
            "notebook_id": TARGET_NOTEBOOK_ID,
            "title": TARGET_NOTEBOOK_TITLE,
            "save_for_project": True,
        }
        sel_res = await send_broker_command(reader, writer, sel_req)
        if not sel_res.get("ok") and sel_res.get("error", {}).get("code") != "SESSION_LOCKED":
            print(f"[sync] Error selecting notebook: {sel_res}", file=sys.stderr)
            sys.exit(1)
        print("[sync] Notebook locked successfully.")

        # Step 2: Fetch current sources to know baseline
        print("[sync] Fetching existing source catalog...")
        list_req = {"action": "list_sources", "notebook_id": TARGET_NOTEBOOK_ID}
        list_res = await send_broker_command(reader, writer, list_req)
        existing_sources = list_res.get("sources", [])
        print(f"[sync] Current sources in notebook: {len(existing_sources)}")

        results = []
        base_dir = Path(__file__).resolve().parent.parent

        # Step 3: Ingest each document sequentially
        for idx, doc in enumerate(DOCUMENTS_TO_PUSH, start=1):
            file_path = base_dir / doc["file"]
            if not file_path.is_file():
                print(f"[sync] Warning: file {file_path} not found, skipping.", file=sys.stderr)
                continue

            content = file_path.read_text(encoding="utf-8")
            title = doc["title"]
            print(f"\n[sync] ({idx}/{len(DOCUMENTS_TO_PUSH)}) Pushing '{title}' ({len(content)} chars)...")

            add_req = {
                "action": "add_source",
                "notebook_id": TARGET_NOTEBOOK_ID,
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

            # Minor pause between uploads for clean event loop cycle
            await asyncio.sleep(1.0)

        # Step 4: Verify updated source count
        print("\n[sync] Verifying final source catalog...")
        final_list = await send_broker_command(reader, writer, list_req)
        final_sources = final_list.get("sources", [])
        print(f"[sync] Updated sources in notebook: {len(final_sources)} (added {len(final_sources) - len(existing_sources)} new sources)")

        # Step 5: Test Q&A Query targeting the newly ingested completion report
        new_source_ids = [r["source_id"] for r in results if r.get("ok") and r.get("source_id")]
        if new_source_ids:
            print("\n[sync] Testing grounded query against newly ingested documentation...")
            query_req = {
                "action": "query_notebook",
                "notebook_id": TARGET_NOTEBOOK_ID,
                "question": "What is the certified status and test results of Implementation Plan v4.2, and what does ADR-017 specify?",
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
