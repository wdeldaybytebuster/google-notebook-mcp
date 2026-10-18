#!/usr/bin/env python3
"""Automated live qualification script exercising all 5 MCP tools against Google Gemini Notebook."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from typing import Any, cast


async def run_live_test(notebook_id: str) -> None:
    env = os.environ.copy()
    env["PYTHONPATH"] = "src"
    env["UV_THREADPOOL_SIZE"] = "3"

    print(f"[*] Starting MCP Client Facade for notebook: {notebook_id}")
    proc = await asyncio.create_subprocess_exec(
        ".venv/bin/python", "-m", "mcp_gateway.cli", "mcp",
        stdin=asyncio.subprocess.PIPE,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    async def send_rpc(method: str, params: dict[str, Any], req_id: int) -> dict[str, Any]:
        req = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write((json.dumps(req) + "\n").encode("utf-8"))
        await proc.stdin.drain()
        line = await proc.stdout.readline()
        if not line:
            stderr_out = await proc.stderr.read() if proc.stderr else b""
            raise RuntimeError(f"Server closed connection unexpectedly. Stderr: {stderr_out.decode('utf-8', errors='replace')}")
        return cast(dict[str, Any], json.loads(line.decode("utf-8").strip()))

    # 1. Initialize
    print("\n--- [STEP 1] initialize ---")
    init_res = await send_rpc(
        "initialize",
        {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "live-tester", "version": "1.0.0"},
        },
        1,
    )
    print(f"[*] Initialize response: {json.dumps(init_res, indent=2)}")

    # Send initialized notification
    notif = {"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}
    assert proc.stdin is not None
    proc.stdin.write((json.dumps(notif) + "\n").encode("utf-8"))
    await proc.stdin.drain()

    # 2. Tool 1: list_notebooks
    print("\n--- [STEP 2] Tool 1: list_notebooks ---")
    t1 = await send_rpc("tools/call", {"name": "list_notebooks", "arguments": {}}, 2)
    print(f"[*] list_notebooks response: {json.dumps(t1, indent=2)}")

    # 3. Tool 2: get_notebook_metadata
    print("\n--- [STEP 3] Tool 2: get_notebook_metadata ---")
    t2 = await send_rpc(
        "tools/call",
        {"name": "get_notebook_metadata", "arguments": {"notebook_id": notebook_id}},
        3,
    )
    print(f"[*] get_notebook_metadata response: {json.dumps(t2, indent=2)}")

    import time
    ts = int(time.time())
    # 4. Tool 3: add_source (Text snippet)
    print("\n--- [STEP 4] Tool 3: add_source ---")
    t3 = await send_rpc(
        "tools/call",
        {
            "name": "add_source",
            "arguments": {
                "notebook_id": notebook_id,
                "idempotency_key": f"live-text-{ts}",
                "source": {
                    "type": "text",
                    "title": "Automated Architecture Document",
                    "content": (
                        "The Gemini Notebook MCP Server uses Chrome-Beta and Manifest V3 "
                        "in-browser fetch execution to preserve hardware TPM DBSC challenge signing."
                    ),
                },
                "wait_until_ready": True,
            },
        },
        4,
    )
    print(f"[*] add_source response: {json.dumps(t3, indent=2)}")

    # 5. Tool 4: list_sources
    print("\n--- [STEP 5] Tool 4: list_sources ---")
    t4 = await send_rpc(
        "tools/call",
        {"name": "list_sources", "arguments": {"notebook_id": notebook_id}},
        5,
    )
    print(f"[*] list_sources response: {json.dumps(t4, indent=2)}")

    # 6. Tool 5: query_notebook
    print("\n--- [STEP 6] Tool 5: query_notebook ---")
    t5 = await send_rpc(
        "tools/call",
        {
            "name": "query_notebook",
            "arguments": {
                "notebook_id": notebook_id,
                "question": "What does the MCP server use to preserve hardware TPM DBSC challenge signing?",
                "request_key": f"live-query-{ts}",
            },
        },
        6,
    )
    print(f"[*] query_notebook response: {json.dumps(t5, indent=2)}")

    proc.terminate()
    await proc.wait()
    print("\n[SUCCESS] All 5 tools executed against live Google backend.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: scripts/live_smoke_test.py <notebook_id>")
        sys.exit(1)
    asyncio.run(run_live_test(sys.argv[1]))
