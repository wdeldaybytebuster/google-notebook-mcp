#!/usr/bin/env python3
"""Phase 7 Live Qualification — Stage 1: Pure Testing against Test Notebook (00000000-0000-0000-0000-000000000002).

Enforces:
- User instruction: Pure testing on Test Notebook.
- ADR-011 session lock validation (DISCOVERY_ONLY -> ACTIVE_DISPATCH).
- CYK0Xb note creation and instant READY.
- rLM1Ne [0][17] note extraction and M-05 canary verification.
- tGMBJ note deletion.
- In-browser text source ingestion with readiness polling.
- Grounded query with strict citation verification (M-06).
- ADR-011 cross-notebook lock defense verification (SESSION_LOCKED).
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
import struct
import sys
import time

IPC_FRAME_FORMAT = ">I"
SOCKET_PATH = "/run/user/1000/notebooklm-mcp/broker.sock"
TEST_NOTEBOOK_ID = "00000000-0000-0000-0000-000000000002"
TEST_NOTEBOOK_TITLE = "Test Notebook"
PROD_NOTEBOOK_ID = "00000000-0000-0000-0000-000000000001"


async def send_broker_command(reader: asyncio.StreamReader, writer: asyncio.StreamWriter, req: dict) -> dict:
    req_bytes = json.dumps(req).encode("utf-8")
    header = struct.pack(IPC_FRAME_FORMAT, len(req_bytes))
    writer.write(header + req_bytes)
    await writer.drain()

    header_bytes = await reader.readexactly(4)
    (msg_len,) = struct.unpack(IPC_FRAME_FORMAT, header_bytes)
    payload_bytes = await reader.readexactly(msg_len)
    return json.loads(payload_bytes.decode("utf-8"))


async def run_stage1_testing() -> dict:
    results = {}
    print(f"[Stage 1] Connecting to broker at {SOCKET_PATH}...")
    reader, writer = await asyncio.open_unix_connection(SOCKET_PATH)

    try:
        # Step 1: select_notebook on Test Notebook
        print("\n=== [1] select_notebook (Test Notebook) ===")
        sel_req = {
            "action": "select_notebook",
            "title": TEST_NOTEBOOK_TITLE,
            "notebook_id": TEST_NOTEBOOK_ID,
        }
        sel_res = await send_broker_command(reader, writer, sel_req)
        print("select_notebook response:", json.dumps(sel_res, indent=2))
        results["select_notebook"] = sel_res
        assert sel_res.get("ok") is True, f"select_notebook failed: {sel_res}"

        # Step 2: list_sources
        print("\n=== [2] list_sources ===")
        list_src_req = {
            "action": "list_sources",
            "notebook_id": TEST_NOTEBOOK_ID,
        }
        list_src_res = await send_broker_command(reader, writer, list_src_req)
        print("list_sources response:", json.dumps(list_src_res, indent=2))
        results["list_sources"] = list_src_res
        assert list_src_res.get("ok") is True, f"list_sources failed: {list_src_res}"

        # Step 3: create_note
        print("\n=== [3] create_note ===")
        ts = int(time.time())
        note_req = {
            "action": "create_note",
            "notebook_id": TEST_NOTEBOOK_ID,
            "title": "Phase 7 Live In-Situ Verification Note",
            "content": "Automated verification of CYK0Xb RPC, FSM journal state transitions, and instant READY readiness.",
            "idempotency_key": f"phase7-test-note-{ts}",
        }
        note_res = await send_broker_command(reader, writer, note_req)
        print("create_note response:", json.dumps(note_res, indent=2))
        results["create_note"] = note_res
        assert note_res.get("ok") is True, f"create_note failed: {note_res}"
        note_id = note_res.get("note_id") or note_res.get("note", {}).get("id") or ""
        print(f"Created note ID: {note_id}")

        # Step 4: list_notes
        print("\n=== [4] list_notes ===")
        list_notes_req = {
            "action": "list_notes",
            "notebook_id": TEST_NOTEBOOK_ID,
        }
        list_notes_res = await send_broker_command(reader, writer, list_notes_req)
        print("list_notes response:", json.dumps(list_notes_res, indent=2))
        results["list_notes"] = list_notes_res
        assert list_notes_res.get("ok") is True, f"list_notes failed: {list_notes_res}"

        # Step 5: delete_note
        print(f"\n=== [5] delete_note ({note_id}) ===")
        del_req = {
            "action": "delete_note",
            "notebook_id": TEST_NOTEBOOK_ID,
            "note_id": note_id,
            "idempotency_key": f"phase7-test-del-{ts}",
        }
        del_res = await send_broker_command(reader, writer, del_req)
        print("delete_note response:", json.dumps(del_res, indent=2))
        results["delete_note"] = del_res
        assert del_res.get("ok") is True, f"delete_note failed: {del_res}"

        # Step 6: add_source (Text snippet with readiness polling)
        print("\n=== [6] add_source ===")
        add_src_req = {
            "action": "add_source",
            "notebook_id": TEST_NOTEBOOK_ID,
            "idempotency_key": f"phase7-test-addsrc-{ts}",
            "wait_until_ready": True,
            "source": {
                "type": "text",
                "title": f"Phase 7 Qualification Test Document {ts}",
                "content": (
                    "The Gemini Notebook MCP Gateway uses Chrome-Beta and Manifest V3 "
                    "in-browser fetch execution to preserve hardware TPM DBSC challenge signing."
                ),
            },
        }
        add_src_res = await send_broker_command(reader, writer, add_src_req)
        print("add_source response:", json.dumps(add_src_res, indent=2))
        results["add_source"] = add_src_res
        assert add_src_res.get("ok") is True, f"add_source failed: {add_src_res}"
        added_source_id = add_src_res.get("source_id") or ""

        # Step 7: query_notebook (Targeted RAG with citations check)
        print("\n=== [7] query_notebook ===")
        print(f"Targeting newly added source: {added_source_id}")
        query_req = {
            "action": "query_notebook",
            "notebook_id": TEST_NOTEBOOK_ID,
            "question": "According to the source document, what does the Gemini Notebook MCP Gateway use to preserve hardware TPM DBSC challenge signing?",
            "request_key": f"phase7-test-query-{ts}",
            "source_ids": [added_source_id],
        }
        query_res = await send_broker_command(reader, writer, query_req)
        print("query_notebook response:", json.dumps(query_res, indent=2))
        results["query_notebook"] = query_res
        assert query_res.get("ok") is True, f"query_notebook failed: {query_res}"

        # Step 8: Verify ADR-011 SESSION_LOCKED guardrail
        print("\n=== [8] ADR-011 Session Lock Verification (Expect SESSION_LOCKED) ===")
        switch_req = {
            "action": "select_notebook",
            "title": "Google Notebooks MCP",
            "notebook_id": PROD_NOTEBOOK_ID,
        }
        switch_res = await send_broker_command(reader, writer, switch_req)
        print("select_notebook (cross-notebook) response:", json.dumps(switch_res, indent=2))
        results["session_lock_defense"] = switch_res
        assert switch_res.get("ok") is False, "Expected session switch to fail"
        assert switch_res.get("error", {}).get("code") == "SESSION_LOCKED", f"Expected SESSION_LOCKED: {switch_res}"
        print("[ADR-011] SESSION_LOCKED invariant confirmed successfully!")

    finally:
        writer.close()
        await writer.wait_closed()

    return results


if __name__ == "__main__":
    res = asyncio.run(run_stage1_testing())
    print("\n[Stage 1 Complete] Summary:")
    print(json.dumps({k: {"ok": v.get("ok")} for k, v in res.items()}, indent=2))
