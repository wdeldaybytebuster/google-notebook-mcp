"""Unit tests for Phase 4: Scotty Chunking, IPC Mutex Exclusivity,
Memory Interlock Governance, and Resumability Caching.

Covers:
- M-02: IPC companion socket mutex preventing interleaving during Scotty chunk streaming.
- Bounded 512 KiB chunk slicing for large file uploads.
- Edge memory safety interlock threshold enforcing 320 MB reserve.
- P-02: Scotty session URL caching in chrome.storage.session and offset resumption.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from pathlib import Path
import subprocess
from typing import Any, cast
from unittest.mock import AsyncMock, patch

import pytest

from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon
from mcp_gateway.broker.session import SessionState
from mcp_gateway.schemas.error import RESOURCE_EXHAUSTED
from mcp_gateway.storage.journal import MutationState

REPO_ROOT = Path(__file__).resolve().parent.parent
PAGE_MAIN_PATH = REPO_ROOT / "src" / "extension" / "page-main.js"
SERVICE_WORKER_PATH = REPO_ROOT / "src" / "extension" / "service_worker.js"


def _run_node_script(script: str) -> dict[str, Any]:
    """Executes a Node.js snippet and returns parsed JSON output."""
    env = dict(os.environ)
    env["NODE_OPTIONS"] = "--max-old-space-size=1024 --max-semi-space-size=128"
    cmd = ["node", "-e", script]
    result = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
        check=True,
        env=env,
    )
    for line in reversed(result.stdout.strip().splitlines()):
        line_s = line.strip()
        if line_s.startswith("{") and line_s.endswith("}"):
            return cast(dict[str, Any], json.loads(line_s))
    return cast(dict[str, Any], json.loads(result.stdout.strip()))


@pytest.fixture
def allowlist_file(tmp_path: Path) -> Path:
    p = tmp_path / "allowlist.json"
    data = {
        "version": 1,
        "provider_mode": "browser",
        "accounts": ["engineer@example.com"],
        "notebooks": ["nb-1", "nb-2"],
    }
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


@pytest.fixture
def broker(tmp_path: Path, allowlist_file: Path) -> BrokerDaemon:
    cfg = BrokerConfig(
        socket_path=str(tmp_path / "test_scotty.sock"),
        allowlist_path=allowlist_file,
        journal_db_path=tmp_path / "test_scotty.db",
    )
    b = BrokerDaemon(cfg)
    b.session_lock.locked_notebook_id = "nb-1"
    b.session_lock.state = SessionState.ACTIVE_DISPATCH
    return b


# ---------------------------------------------------------------------------
# M-02: IPC Companion Socket Mutex & Interleaving Prevention
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_companion_ipc_mutex_interleaving_prevention(broker: BrokerDaemon) -> None:
    """Verify that socket writes from concurrent operations (list_notebooks,

    get_notebook_metadata) cannot interleave during multi-chunk streaming (M-02).
    """
    written_frames: list[str] = []
    chunk_send_events: list[str] = []

    async def mock_send(
        command: str,
        payload: dict[str, Any],
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        if command == "scotty_chunk":
            idx = payload.get("chunkIndex")
            written_frames.append(f"scotty_chunk_{idx}")
            chunk_send_events.append(f"start_chunk_{idx}")
            # Simulate network write/drain delay during chunk transfer
            await asyncio.sleep(0.02)
            chunk_send_events.append(f"end_chunk_{idx}")
            return {"ok": True, "source_id": payload.get("sourceId")}
        elif command == "batchexecute":
            rpc = payload.get("rpcId")
            written_frames.append(f"batchexecute_{rpc}")
            return {"ok": True, "body": ")]}'\n[[[\"wrb.fr\",\"" + str(rpc) + "\",\"[]\",null,null,null,null,1]]]"}
        return {"ok": True}

    # 4 chunks of data
    total_bytes = 4 * 512 * 1024
    file_bytes = b"A" * total_bytes

    with patch.object(broker, "send_to_companion", side_effect=mock_send):
        # Task 1: multi-chunk Scotty stream
        async def run_streaming() -> dict[str, Any]:
            return await broker._stream_scotty_chunks(
                source_id="src-concurrent-1",
                filename="large.dat",
                notebook_id="nb-1",
                file_bytes=file_bytes,
            )

        # Task 2: concurrent get_notebook_metadata
        async def run_metadata() -> dict[str, Any]:
            await asyncio.sleep(0.01)  # start right while streaming has begun
            return await broker.send_to_companion_exclusive(
                "batchexecute",
                {"rpcId": "rLM1Ne", "notebookId": "nb-1"},
            )

        # Task 3: concurrent list_notebooks
        async def run_list() -> dict[str, Any]:
            await asyncio.sleep(0.01)  # start right while streaming has begun
            return await broker.send_to_companion_exclusive(
                "batchexecute",
                {"rpcId": "wXbhsf"},
            )

        res_stream, res_meta, res_list = await asyncio.gather(
            run_streaming(),
            run_metadata(),
            run_list(),
        )

    assert res_stream["ok"] is True
    assert res_meta["ok"] is True
    assert res_list["ok"] is True

    # Critical invariant: All 4 scotty_chunks must be transmitted consecutively
    # without ANY batchexecute_rLM1Ne or batchexecute_wXbhsf interleaved between them.
    chunk_indices = [
        i for i, f in enumerate(written_frames) if f.startswith("scotty_chunk_")
    ]
    assert len(chunk_indices) == 4
    # Indices must be strictly contiguous in the recorded sequence
    assert chunk_indices == list(range(chunk_indices[0], chunk_indices[0] + 4))

    expected_chunk_sequence = [
        "scotty_chunk_0",
        "scotty_chunk_1",
        "scotty_chunk_2",
        "scotty_chunk_3",
    ]
    actual_subsequence = written_frames[chunk_indices[0] : chunk_indices[0] + 4]
    assert actual_subsequence == expected_chunk_sequence


# ---------------------------------------------------------------------------
# Bounded 512 KiB Chunk Slicing
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_scotty_512k_chunk_slicing(broker: BrokerDaemon) -> None:
    """Verify that a 1.5 MiB file is sliced into exactly 3 chunks of <= 512 KiB each,

    with correct indices, totalChunks, and isLastChunk flags.
    """
    total_len = int(1.5 * 1024 * 1024)  # 1,572,864 bytes
    test_data = os.urandom(total_len)

    sent_chunks: list[dict[str, Any]] = []

    async def mock_send(
        command: str,
        payload: dict[str, Any],
        timeout_seconds: float = 60.0,
    ) -> dict[str, Any]:
        if command == "scotty_chunk":
            sent_chunks.append(payload)
            return {"ok": True, "source_id": payload.get("sourceId")}
        return {"ok": True}

    with patch.object(broker, "send_to_companion", side_effect=mock_send):
        res = await broker._stream_scotty_chunks(
            source_id="src-slice-test",
            filename="firmware.img",
            notebook_id="nb-1",
            file_bytes=test_data,
        )

    assert res["ok"] is True
    assert res["source_id"] == "src-slice-test"

    # Exactly 3 chunks (512 KiB, 512 KiB, 512 KiB)
    assert len(sent_chunks) == 3

    reconstructed_bytes = bytearray()
    for idx, chunk in enumerate(sent_chunks):
        assert chunk["sourceId"] == "src-slice-test"
        assert chunk["filename"] == "firmware.img"
        assert chunk["notebookId"] == "nb-1"
        assert chunk["chunkIndex"] == idx
        assert chunk["totalChunks"] == 3

        chunk_data = base64.b64decode(chunk["chunkData"])
        assert len(chunk_data) <= 512 * 1024
        assert len(chunk_data) == 512 * 1024
        reconstructed_bytes.extend(chunk_data)

        if idx == 2:
            assert chunk["isLastChunk"] is True
        else:
            assert chunk["isLastChunk"] is False

    # Fully bitwise identical to source payload
    assert bytes(reconstructed_bytes) == test_data


# ---------------------------------------------------------------------------
# Edge Memory Safety Interlock Threshold
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_interlock_threshold(broker: BrokerDaemon) -> None:
    """Mock available RAM below 320 MB; verify upload aborts with RESOURCE_EXHAUSTED."""
    # 200 MB available (strictly below the 320 MB safety reserve)
    broker._mock_available_memory_bytes = 200 * 1024 * 1024

    assert broker._check_memory_safety(required_bytes=512 * 1024) is False

    # 1. Verify _stream_scotty_chunks aborts immediately
    chunk_res = await broker._stream_scotty_chunks(
        source_id="src-mem-fail",
        filename="big.iso",
        notebook_id="nb-1",
        file_bytes=b"X" * (1024 * 1024),
    )
    assert chunk_res["ok"] is False
    assert chunk_res["error"]["code"] == RESOURCE_EXHAUSTED
    assert chunk_res["error"]["retryable"] is True
    assert "320 MB safety reserve" in chunk_res["error"]["message"]

    # 2. Verify add_source file upload aborts via dispatch
    res = await broker.dispatch({
        "action": "add_source",
        "notebook_id": "nb-1",
        "idempotency_key": "mem-abort-key-1",
        "source": {
            "type": "file",
            "title": "kernel.bin",
            "content": base64.b64encode(b"Z" * 1024).decode("ascii"),
        },
    })

    assert res["ok"] is False
    assert res["error"]["code"] == RESOURCE_EXHAUSTED
    assert res["error"]["retryable"] is True
    assert "320 MB safety reserve" in res["error"]["message"]

    # Journal should reflect the rejection
    record = broker.journal.get("mem-abort-key-1")
    assert record is not None
    assert record.state == MutationState.REJECTED


# ---------------------------------------------------------------------------
# P-02: Scotty Session URL Caching & Resumption (JavaScript)
# ---------------------------------------------------------------------------


def test_scotty_session_url_caching_and_resumption_js() -> None:
    """Test JS logic for session URL caching in chrome.storage.session and

    resuming from server offset (P-02).
    """
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync('{SERVICE_WORKER_PATH}', 'utf8');

    // In-memory mock for chrome APIs and chrome.storage.session
    const storageStore = new Map();
    global.chrome = {{
      alarms: {{ onAlarm: {{ addListener: () => {{}} }}, create: () => {{}} }},
      runtime: {{
        onStartup: {{ addListener: () => {{}} }},
        onInstalled: {{ addListener: () => {{}} }},
        onMessage: {{ addListener: () => {{}} }},
        connectNative: () => ({{
          onMessage: {{ addListener: () => {{}} }},
          onDisconnect: {{ addListener: () => {{}} }},
          postMessage: () => {{}}
        }})
      }},
      tabs: {{ onUpdated: {{ addListener: () => {{}} }} }},
      storage: {{
        session: {{
          get: async (key) => ({{ [key]: storageStore.get(key) }}),
          set: async (obj) => {{ for (const [k, v] of Object.entries(obj)) storageStore.set(k, v); }},
          remove: async (key) => {{ storageStore.delete(key); }},
        }}
      }}
    }};

    eval(code);

    (async () => {{
      const notebookId = 'nb-test-resumable';
      const sourceId = 'src-test-resumable';
      const sessionKey = getSessionStorageKey(notebookId, sourceId);
      const fakeSessionUrl = 'https://upload.scotty.test/session/sess_98765';

      // 1024 bytes payload
      const testBytes = new Uint8Array(1024);
      for (let i = 0; i < 1024; i++) testBytes[i] = i % 256;

      const fetchCalls = [];

      // Mock fetch for Attempt 1: Upload init succeeds, but upload stream throws network error
      global.fetch = async (url, options) => {{
        fetchCalls.push({{ url, command: options?.headers?.['X-Goog-Upload-Command'], offset: options?.headers?.['X-Goog-Upload-Offset'] }});

        if (url.includes('create_session')) {{
          return {{
            headers: {{
              get: (h) => (h.toLowerCase() === 'x-goog-upload-url' ? fakeSessionUrl : null)
            }}
          }};
        }}

        if (url === fakeSessionUrl && options?.headers?.['X-Goog-Upload-Command'] === 'upload, finalize') {{
          throw new Error('Connection reset mid-stream');
        }}

        throw new Error('Unexpected URL: ' + url);
      }};

      // Execute Attempt 1 -> Fails mid-stream
      const attempt1Result = await executeResumableScottyUpload(sourceId, 'doc.pdf', notebookId, testBytes, 0);

      // Verify Attempt 1 failed with stream error
      const attempt1Failed = (attempt1Result.ok === false && attempt1Result.error.code === 'UPLOAD_STREAM_ERROR');

      // Verify session URL was cached in chrome.storage.session
      const cachedSessionAfterAttempt1 = storageStore.get(sessionKey);

      // Mock fetch for Attempt 2: Query session offset returns offset 512, then upload succeeds
      let resumedOffsetReceived = null;
      let resumedPayloadLength = null;

      global.fetch = async (url, options) => {{
        const cmd = options?.headers?.['X-Goog-Upload-Command'];
        fetchCalls.push({{ url, command: cmd, offset: options?.headers?.['X-Goog-Upload-Offset'] }});

        if (url === fakeSessionUrl && cmd === 'query') {{
          return {{
            headers: {{
              get: (h) => {{
                const lh = h.toLowerCase();
                if (lh === 'x-goog-upload-status') return 'active';
                if (lh === 'x-goog-upload-offset') return '512';
                return null;
              }}
            }}
          }};
        }}

        if (url === fakeSessionUrl && cmd === 'upload, finalize') {{
          resumedOffsetReceived = options.headers['X-Goog-Upload-Offset'];
          resumedPayloadLength = options.body.byteLength;
          return {{
            headers: {{
              get: (h) => (h.toLowerCase() === 'x-goog-upload-status' ? 'final' : null)
            }}
          }};
        }}

        throw new Error('Unexpected URL on resumption: ' + url);
      }};

      // Execute Attempt 2 -> Resumes from offset 512
      const attempt2Result = await executeResumableScottyUpload(sourceId, 'doc.pdf', notebookId, testBytes, 0);

      // Verify session key evicted from storage after completion
      const sessionEvictedAfterSuccess = !storageStore.has(sessionKey);

      console.log(JSON.stringify({{
        sessionKey,
        attempt1Failed,
        cachedSessionAfterAttempt1,
        attempt2Ok: attempt2Result.ok,
        resumedOffsetReceived,
        resumedPayloadLength,
        sessionEvictedAfterSuccess,
        totalFetchCalls: fetchCalls.length
      }}));
    }})().catch(err => {{
      console.error(err);
      process.exit(1);
    }});
    """

    out = _run_node_script(script)

    assert out["sessionKey"] == "scotty_session_nb-test-resumable_src-test-resumable"
    assert out["attempt1Failed"] is True
    assert out["cachedSessionAfterAttempt1"] == "https://upload.scotty.test/session/sess_98765"
    assert out["attempt2Ok"] is True
    assert out["resumedOffsetReceived"] == "512"
    # Total payload was 1024 bytes, resumed slice was 1024 - 512 = 512 bytes
    assert out["resumedPayloadLength"] == 512
    assert out["sessionEvictedAfterSuccess"] is True


def test_scotty_chunk_collector_js() -> None:
    """Verify that multi-chunk payloads transmitted via scotty_chunk are collected

    and reassembled into full byte payloads before resumable upload.
    """
    script = f"""
    const fs = require('fs');
    const code = fs.readFileSync('{SERVICE_WORKER_PATH}', 'utf8');

    const storageStore = new Map();
    global.chrome = {{
      alarms: {{ onAlarm: {{ addListener: () => {{}} }}, create: () => {{}} }},
      runtime: {{
        onStartup: {{ addListener: () => {{}} }},
        onInstalled: {{ addListener: () => {{}} }},
        onMessage: {{ addListener: () => {{}} }},
        connectNative: () => ({{
          onMessage: {{ addListener: () => {{}} }},
          onDisconnect: {{ addListener: () => {{}} }},
          postMessage: () => {{}}
        }})
      }},
      tabs: {{ onUpdated: {{ addListener: () => {{}} }} }},
      storage: {{
        session: {{
          get: async (key) => ({{ [key]: storageStore.get(key) }}),
          set: async (obj) => {{ for (const [k, v] of Object.entries(obj)) storageStore.set(k, v); }},
          remove: async (key) => {{ storageStore.delete(key); }},
        }}
      }}
    }};

    eval(code);

    (async () => {{
      const sourceId = 'src-chunk-collector-test';
      const notebookId = 'nb-chunk-test';
      const fakeSessionUrl = 'https://upload.scotty.test/session/collector_sess';

      let uploadedByteCount = null;

      global.fetch = async (url, options) => {{
        if (url.includes('create_session')) {{
          return {{
            headers: {{
              get: (h) => (h.toLowerCase() === 'x-goog-upload-url' ? fakeSessionUrl : null)
            }}
          }};
        }}
        if (url === fakeSessionUrl) {{
          uploadedByteCount = options.body.byteLength;
          return {{
            headers: {{
              get: (h) => (h.toLowerCase() === 'x-goog-upload-status' ? 'final' : null)
            }}
          }};
        }}
        throw new Error('Unexpected URL: ' + url);
      }};

      // Chunk 0 (100 bytes)
      const chunk0B64 = Buffer.from('A'.repeat(100)).toString('base64');
      const res0 = await handleScottyChunkSW({{
        sourceId,
        filename: 'report.pdf',
        notebookId,
        chunkIndex: 0,
        totalChunks: 2,
        isLastChunk: false,
        chunkData: chunk0B64,
        authuser: 0
      }});

      // Chunk 1 (Last, 150 bytes)
      const chunk1B64 = Buffer.from('B'.repeat(150)).toString('base64');
      const res1 = await handleScottyChunkSW({{
        sourceId,
        filename: 'report.pdf',
        notebookId,
        chunkIndex: 1,
        totalChunks: 2,
        isLastChunk: true,
        chunkData: chunk1B64,
        authuser: 0
      }});

      console.log(JSON.stringify({{
        res0Ok: res0.ok,
        res0ChunkIndex: res0.chunkIndex,
        res1Ok: res1.ok,
        res1SourceId: res1.sourceId,
        uploadedByteCount
      }}));
    }})().catch(err => {{
      console.error(err);
      process.exit(1);
    }});
    """

    out = _run_node_script(script)
    assert out["res0Ok"] is True
    assert out["res0ChunkIndex"] == 0
    assert out["res1Ok"] is True
    assert out["res1SourceId"] == "src-chunk-collector-test"
    # Total uploaded bytes = 100 + 150 = 250 bytes
    assert out["uploadedByteCount"] == 250

