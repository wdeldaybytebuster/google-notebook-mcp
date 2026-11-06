"""Comprehensive tests for Phase 10 Studio Artifact Retrieval Engine.

Covers:
- list_artifacts with type filtering, pagination, and Invariant 4 schema drift canaries.
- get_artifact_metadata for Invariant 1 GENERATING (operation_handle op_art_<id>) and READY states.
- extract_artifact: formatted Markdown text output vs Invariant 2 zero-memory tmpfs media streaming.
- Strict path traversal & UUID regex validation.
- Atomic staging (.part_<session_id>) and atomic os.replace commit with 0o600 permissions.
- Rollback and unlinking on interrupted/cancelled downloads.
- ACK backpressure chunk handling.
- Service worker JS stream slicing, safe Base64 encoding, and cancellation frames.
"""

from __future__ import annotations

import base64
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, AsyncGenerator
from unittest.mock import AsyncMock, patch

import pytest

from mcp_gateway.broker.broker import BrokerConfig, BrokerDaemon
from mcp_gateway.schemas.error import (
    INVALID_ARGUMENT,
    NOT_FOUND,
    UPSTREAM_SCHEMA_DRIFT,
)

# Mandatory Testing Constraint:
# Must use the "Test Notebook" (3e3c08b5-7e5c-4189-9923-81933a256f54).
# NEVER touch b61be5ed-8360-42cb-bdd6-328160a0eb0f.
TEST_NOTEBOOK_ID = "3e3c08b5-7e5c-4189-9923-81933a256f54"
REPO_ROOT = Path(__file__).resolve().parent.parent
SERVICE_WORKER_PATH = REPO_ROOT / "src" / "extension" / "service_worker.js"


@pytest.fixture
async def mock_broker(tmp_path: Path) -> AsyncGenerator[BrokerDaemon, None]:
    """Yields a configured BrokerDaemon instance with TEST_NOTEBOOK_ID allowlisted."""
    allowlist_file = tmp_path / "allowlist.json"
    data = {
        "version": 1,
        "provider_mode": "browser",
        "accounts": ["test@example.com"],
        "notebooks": [TEST_NOTEBOOK_ID],
    }
    allowlist_file.write_text(json.dumps(data), encoding="utf-8")

    cfg = BrokerConfig(
        allowlist_path=allowlist_file,
        socket_path=str(tmp_path / "test_broker.sock"),
        journal_db_path=tmp_path / "journal.db",
        capability_secret=b"test-secret-artifacts-32bytes-ok",
    )
    daemon = BrokerDaemon(config=cfg)
    yield daemon
    await daemon.stop()


def _make_rlm_wire_body(container: list[Any]) -> str:
    """Helper to frame a container list into Google's chunked batchexecute wire format."""
    return ")]}'\n" + json.dumps([
        [
            "wrb.fr",
            "rLM1Ne",
            json.dumps([container]),
        ]
    ])


@pytest.mark.asyncio
async def test_list_artifacts_success_and_type_filters(mock_broker: BrokerDaemon) -> None:
    """Verifies list_artifacts correctly parses container[18] and applies type filtering."""
    await mock_broker.session_lock.select_notebook(TEST_NOTEBOOK_ID, is_allowed=True)

    container: list[Any] = [None] * 20
    artifact_rows = [
        ["art-audio-1", "Deep Dive Overview", "AUDIO", 2, "https://storage.googleapis.com/audio1.mp3", None],
        ["art-video-1", "Video Summary", "VIDEO", 2, "https://storage.googleapis.com/video1.mp4", None],
        ["art-report-1", "Executive Report", "REPORT", 2, None, "# Executive Report\n\nFull analysis."],
        ["art-guide-1", "Study Guide", "STUDY_GUIDE", 2, None, "# Study Guide\n\nChapter notes."],
    ]
    container[18] = artifact_rows

    wire_body = _make_rlm_wire_body(container)
    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": wire_body}

        # 1. Unfiltered listing returns all 4 artifacts
        res = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
        })
        assert res["ok"] is True
        assert res["total_count"] == 4
        assert len(res["artifacts"]) == 4

        # 2. Filter by AUDIO returns only audio artifact
        res_audio = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_type_filter": "AUDIO",
        })
        assert res_audio["ok"] is True
        assert len(res_audio["artifacts"]) == 1
        assert res_audio["artifacts"][0]["id"] == "art-audio-1"
        assert res_audio["artifacts"][0]["type"] == "AUDIO"

        # 3. Filter by VIDEO returns only video artifact
        res_video = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_type_filter": "video",
        })
        assert res_video["ok"] is True
        assert len(res_video["artifacts"]) == 1
        assert res_video["artifacts"][0]["id"] == "art-video-1"

        # 4. Filter by REPORT returns only report artifact
        res_report = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_type_filter": "REPORT",
        })
        assert res_report["ok"] is True
        assert len(res_report["artifacts"]) == 1
        assert res_report["artifacts"][0]["id"] == "art-report-1"

        # 5. Filter by ALL returns all artifacts
        res_all = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_type_filter": "ALL",
        })
        assert res_all["ok"] is True
        assert len(res_all["artifacts"]) == 4


@pytest.mark.asyncio
async def test_list_artifacts_schema_drift_canaries(mock_broker: BrokerDaemon) -> None:
    """Verifies Invariant 4 loud canaries (UPSTREAM_SCHEMA_DRIFT) when envelope structure changes."""
    await mock_broker.session_lock.select_notebook(TEST_NOTEBOOK_ID, is_allowed=True)

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        # Canary 1: Missing rLM1Ne record entirely
        mock_send.return_value = {"ok": True, "body": ")]}'\n" + json.dumps([["wrb.fr", "other_rpc", "[]"]])}
        res_missing = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
        })
        assert res_missing["ok"] is False
        assert res_missing["error"]["code"] == UPSTREAM_SCHEMA_DRIFT
        assert "rLM1Ne record missing" in res_missing["error"]["message"]

        # Canary 2: Malformed envelope (not a list of list)
        mock_send.return_value = {"ok": True, "body": ")]}'\n" + json.dumps([["wrb.fr", "rLM1Ne", json.dumps("not-a-list")]])}
        res_malformed = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
        })
        assert res_malformed["ok"] is False
        assert res_malformed["error"]["code"] == UPSTREAM_SCHEMA_DRIFT
        assert "Invalid rLM1Ne response envelope structure" in res_malformed["error"]["message"]

        # Canary 3: Truncated container (length <= 18)
        short_container: list[Any] = [None] * 18
        mock_send.return_value = {"ok": True, "body": _make_rlm_wire_body(short_container)}
        res_truncated = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
        })
        assert res_truncated["ok"] is False
        assert res_truncated["error"]["code"] == UPSTREAM_SCHEMA_DRIFT
        assert "expected > 18 for artifacts array" in res_truncated["error"]["message"]

        # Canary 4: container[18] is not a list (e.g., int or string)
        corrupt_container: list[Any] = [None] * 20
        corrupt_container[18] = "unexpected-string"
        mock_send.return_value = {"ok": True, "body": _make_rlm_wire_body(corrupt_container)}
        res_non_array = await mock_broker.dispatch({
            "action": "list_artifacts",
            "notebook_id": TEST_NOTEBOOK_ID,
        })
        assert res_non_array["ok"] is False
        assert res_non_array["error"]["code"] == UPSTREAM_SCHEMA_DRIFT
        assert "container[18] is not an array" in res_non_array["error"]["message"]


@pytest.mark.asyncio
async def test_get_artifact_metadata_generating_vs_ready(mock_broker: BrokerDaemon) -> None:
    """Verifies Invariant 1: non-blocking operation handle on GENERATING, and direct metadata on READY."""
    await mock_broker.session_lock.select_notebook(TEST_NOTEBOOK_ID, is_allowed=True)

    container: list[Any] = [None] * 20
    artifact_rows = [
        ["art-gen-100", "Pending Podcast", "AUDIO", 1, None, None],  # status 1 = GENERATING
        ["art-ready-200", "Finished Guide", "STUDY_GUIDE", 2, None, "# Guide Content"],  # status 2 = READY
    ]
    container[18] = artifact_rows
    wire_body = _make_rlm_wire_body(container)

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": wire_body}

        # 1. GENERATING status must return operation_handle op_art_<id>
        res_gen = await mock_broker.dispatch({
            "action": "get_artifact_metadata",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_id": "art-gen-100",
        })
        assert res_gen["ok"] is True
        assert res_gen["status"] == "GENERATING"
        assert res_gen["operation_handle"] == "op_art_art-gen-100"
        assert "operation_handle" in res_gen["message"]
        assert res_gen["artifact"]["id"] == "art-gen-100"

        # 2. READY status must return artifact metadata directly without operation_handle
        res_ready = await mock_broker.dispatch({
            "action": "get_artifact_metadata",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_id": "art-ready-200",
        })
        assert res_ready["ok"] is True
        assert res_ready["status"] == "READY"
        assert "operation_handle" not in res_ready
        assert res_ready["artifact"]["title"] == "Finished Guide"

        # 3. Non-existent artifact ID returns NOT_FOUND
        res_missing = await mock_broker.dispatch({
            "action": "get_artifact_metadata",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_id": "art-unknown-999",
        })
        assert res_missing["ok"] is False
        assert res_missing["error"]["code"] == NOT_FOUND


@pytest.mark.asyncio
async def test_extract_artifact_text_vs_binary_tmpfs(mock_broker: BrokerDaemon) -> None:
    """Verifies text extraction directly returns Markdown text, while binary extraction outputs to tmpfs."""
    await mock_broker.session_lock.select_notebook(TEST_NOTEBOOK_ID, is_allowed=True)

    container: list[Any] = [None] * 20
    artifact_rows = [
        ["art-report-50", "Briefing Doc", "REPORT", 2, None, "# Briefing Doc\n\nExecutive points."],
        ["art-audio-50", "Studio Audio", "AUDIO", 2, "https://storage.googleapis.com/audio50.mp3", None],
        ["art-gen-50", "Rendering Video", "VIDEO", 1, None, None],
    ]
    container[18] = artifact_rows
    wire_body = _make_rlm_wire_body(container)

    with patch.object(mock_broker, "send_to_companion", new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"ok": True, "body": wire_body}

        # 1. Text deliverable returns formatted Markdown directly
        res_text = await mock_broker.dispatch({
            "action": "extract_artifact",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_id": "art-report-50",
            "output_format": "MARKDOWN",
        })
        assert res_text["ok"] is True
        assert res_text["format"] == "MARKDOWN"
        assert "Executive points." in res_text["content"]
        assert res_text["type"] == "REPORT"

        # 2. Binary deliverable extracts to tmpfs with 0o600 permissions
        res_binary = await mock_broker.dispatch({
            "action": "extract_artifact",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_id": "art-audio-50",
        })
        assert res_binary["ok"] is True
        assert res_binary["format"] == "FILE_PATH"
        assert res_binary["type"] == "AUDIO"
        file_path = Path(res_binary["file_path"])
        assert file_path.exists()
        assert file_path.parent == Path("/tmp/notebooklm-mcp-artifacts")
        if sys.platform != "win32":
            assert (file_path.stat().st_mode & 0o777) == 0o600

        # 3. Extracting an artifact that is still GENERATING fails non-blocking with OPERATION_IN_PROGRESS
        res_gen = await mock_broker.dispatch({
            "action": "extract_artifact",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_id": "art-gen-50",
        })
        assert res_gen["ok"] is False
        assert res_gen["error"]["code"] == "OPERATION_IN_PROGRESS"
        assert res_gen["error"]["operation_handle"] == "op_art_art-gen-50"
        assert res_gen["error"]["retryable"] is True


@pytest.mark.asyncio
async def test_path_traversal_attack_rejection(mock_broker: BrokerDaemon) -> None:
    """Verifies that malicious or non-sanitized artifact_id and notebook_id are rejected."""
    await mock_broker.session_lock.select_notebook(TEST_NOTEBOOK_ID, is_allowed=True)

    malicious_ids = [
        "../../etc/passwd",
        "art/../secret",
        "art_id_with_space ",
        "art;rm -rf /",
        "art<script>alert(1)</script>",
        "a" * 65,  # Exceeds 64 chars
    ]

    for bad_id in malicious_ids:
        # Check in get_artifact_metadata
        res_meta = await mock_broker.dispatch({
            "action": "get_artifact_metadata",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_id": bad_id,
        })
        assert res_meta["ok"] is False
        assert res_meta["error"]["code"] == INVALID_ARGUMENT

        # Check in extract_artifact
        res_ext = await mock_broker.dispatch({
            "action": "extract_artifact",
            "notebook_id": TEST_NOTEBOOK_ID,
            "artifact_id": bad_id,
        })
        assert res_ext["ok"] is False
        assert res_ext["error"]["code"] == INVALID_ARGUMENT

        # Check in artifact_chunk
        res_chunk = await mock_broker.dispatch({
            "action": "artifact_chunk",
            "artifact_id": bad_id,
            "session_id": "sess-valid-1",
            "chunk_base64": "",
            "is_last": True,
        })
        assert res_chunk["ok"] is False
        assert res_chunk["error"]["code"] == INVALID_ARGUMENT


@pytest.mark.asyncio
async def test_artifact_chunk_ack_backpressure_and_atomic_commit(mock_broker: BrokerDaemon) -> None:
    """Verifies staging file creation with mode 0o600, chunk ACK reply, and atomic commit on is_last."""
    art_id = "art-chunk-test-1"
    session_id = "sess-abc-123"
    tmpfs_dir = Path("/tmp/notebooklm-mcp-artifacts")
    staging_file = tmpfs_dir / f"art_{art_id}.mp3.part_{session_id}"
    final_file = tmpfs_dir / f"art_{art_id}.mp3"

    # Cleanup potential previous artifacts
    staging_file.unlink(missing_ok=True)
    final_file.unlink(missing_ok=True)

    # Chunk 0: 64 bytes
    chunk0_data = b"A" * 64
    chunk0_b64 = base64.b64encode(chunk0_data).decode("ascii")

    res0 = await mock_broker.dispatch({
        "action": "artifact_chunk",
        "artifact_id": art_id,
        "session_id": session_id,
        "artifact_type": "AUDIO",
        "chunk_index": 0,
        "chunk_base64": chunk0_b64,
        "is_last": False,
    })

    assert res0["ok"] is True
    assert res0["action"] == "artifact_chunk_ack"
    assert res0["chunk_index"] == 0
    assert res0["bytes_written"] == 64
    assert res0["is_last"] is False

    # Verify staging file exists with mode 0o600, final file does not exist yet
    assert staging_file.exists()
    if sys.platform != "win32":
        assert (staging_file.stat().st_mode & 0o777) == 0o600
    assert not final_file.exists()

    # Chunk 1: 128 bytes, is_last=True -> triggers atomic commit
    chunk1_data = b"B" * 128
    chunk1_b64 = base64.b64encode(chunk1_data).decode("ascii")

    res1 = await mock_broker.dispatch({
        "action": "artifact_chunk",
        "artifact_id": art_id,
        "session_id": session_id,
        "artifact_type": "AUDIO",
        "chunk_index": 1,
        "chunk_base64": chunk1_b64,
        "is_last": True,
    })

    assert res1["ok"] is True
    assert res1["action"] == "artifact_chunk_ack"
    assert res1["chunk_index"] == 1
    assert res1["bytes_written"] == 192  # 64 + 128
    assert res1["is_last"] is True
    assert res1["file_path"] == str(final_file)

    # Verify atomic commit: staging file gone, final file committed with mode 0o600
    assert not staging_file.exists()
    assert final_file.exists()
    assert final_file.stat().st_size == 192
    if sys.platform != "win32":
        assert (final_file.stat().st_mode & 0o777) == 0o600

    # Cleanup
    final_file.unlink(missing_ok=True)


@pytest.mark.asyncio
async def test_atomic_staging_and_rollback_on_interrupted_download(mock_broker: BrokerDaemon) -> None:
    """Verifies that an aborted download unlinks the staging file immediately."""
    art_id = "art-rollback-test-2"
    session_id = "sess-rollback-456"
    tmpfs_dir = Path("/tmp/notebooklm-mcp-artifacts")
    staging_file = tmpfs_dir / f"art_{art_id}.mp4.part_{session_id}"
    final_file = tmpfs_dir / f"art_{art_id}.mp4"

    staging_file.unlink(missing_ok=True)
    final_file.unlink(missing_ok=True)

    # Send first chunk
    chunk_data = b"PartialVideoData"
    res0 = await mock_broker.dispatch({
        "action": "artifact_chunk",
        "artifact_id": art_id,
        "session_id": session_id,
        "artifact_type": "VIDEO",
        "chunk_index": 0,
        "chunk_base64": base64.b64encode(chunk_data).decode("ascii"),
        "is_last": False,
    })
    assert res0["ok"] is True
    assert staging_file.exists()

    # Simulate cancellation event from companion
    cancel_res = await mock_broker.dispatch({
        "action": "artifact_chunk_cancel",
        "artifact_id": art_id,
        "session_id": session_id,
        "artifact_type": "VIDEO",
    })
    assert cancel_res["ok"] is True
    assert cancel_res["cancelled"] is True

    # Staging file must be completely deleted
    assert not staging_file.exists()
    assert not final_file.exists()


def test_service_worker_download_artifact_js() -> None:
    """Verifies service_worker.js stream chunking, Base64 conversion, and cancellation in Node."""
    js_test_script = f"""
    const fs = require('fs');
    const code = fs.readFileSync({json.dumps(str(SERVICE_WORKER_PATH))}, 'utf8');

    let nativeOnMessageListener = null;
    const postedToNative = [];

    global.chrome = {{
      alarms: {{ onAlarm: {{ addListener: () => {{}} }}, create: () => {{}} }},
      tabs: {{
        onUpdated: {{ addListener: () => {{}} }},
        query: () => [],
        remove: () => Promise.resolve(),
      }},
      scripting: {{ executeScript: () => Promise.resolve() }},
      storage: {{
        local: {{ get: () => Promise.resolve({{}}), set: () => Promise.resolve() }},
      }},
      runtime: {{
        id: 'mock-ext-id',
        lastError: null,
        onStartup: {{ addListener: () => {{}} }},
        onInstalled: {{ addListener: () => {{}} }},
        onMessage: {{ addListener: () => {{}} }},
        connectNative: () => ({{
          onMessage: {{ addListener: (fn) => {{ nativeOnMessageListener = fn; }} }},
          onDisconnect: {{ addListener: () => {{}} }},
          postMessage: (msg) => {{
            postedToNative.push(msg);
            // Simulate broker ACK replies for artifact_chunk
            if (msg && msg.action === 'artifact_chunk') {{
              setTimeout(() => nativeOnMessageListener({{
                ok: true,
                requestId: msg.requestId,
                action: 'artifact_chunk_ack',
                bytes_written: 100,
                file_path: '/tmp/notebooklm-mcp-artifacts/art_mock.mp3'
              }}), 5);
            }} else if (msg && msg.action === 'artifact_chunk_cancel') {{
              setTimeout(() => nativeOnMessageListener({{
                ok: true,
                requestId: msg.requestId,
                action: 'artifact_chunk_cancel_ack'
              }}), 5);
            }}
          }}
        }})
      }}
    }};

    eval(code);

    async function runTests() {{
      // 1. Verify uint8ArrayToBase64 on 65,536+ bytes without stack overflow
      const largeBytes = new Uint8Array(70000);
      largeBytes.fill(65); // 'A'
      const base64Str = globalThis.uint8ArrayToBase64(largeBytes);
      if (!base64Str || base64Str.length < 90000) {{
        throw new Error('uint8ArrayToBase64 failed on large buffer');
      }}

      // 2. Mock fetch with readable stream
      const chunk1 = new Uint8Array(100);
      chunk1.fill(66); // 'B'
      let readCount = 0;

      global.fetch = async (url) => {{
        if (url.includes('error-network')) {{
          throw new Error('Simulated network failure');
        }}
        return {{
          ok: true,
          status: 200,
          statusText: 'OK',
          body: {{
            getReader: () => ({{
              read: async () => {{
                if (readCount++ === 0) {{
                  return {{ done: false, value: chunk1 }};
                }}
                return {{ done: true, value: undefined }};
              }},
              cancel: async () => {{}}
            }})
          }}
        }};
      }};

      // 3. Test handleDownloadArtifact success flow
      await globalThis.handleDownloadArtifact('req-download-1', {{
        url: 'https://storage.googleapis.com/test.mp3',
        artifactId: 'art-sw-1',
        sessionId: 'sess-sw-1',
        artifactType: 'AUDIO'
      }});

      const completionFrame = postedToNative.find(m => m.requestId === 'req-download-1');
      if (!completionFrame || !completionFrame.ok) {{
        throw new Error('handleDownloadArtifact did not complete successfully: ' + JSON.stringify(completionFrame));
      }}

      // 4. Test handleDownloadArtifact network error cancellation
      await globalThis.handleDownloadArtifact('req-download-err', {{
        url: 'https://storage.googleapis.com/error-network.mp3',
        artifactId: 'art-sw-err',
        sessionId: 'sess-sw-err',
        artifactType: 'AUDIO'
      }});

      const cancelFrame = postedToNative.find(m => m.action === 'artifact_chunk_cancel');
      if (!cancelFrame) {{
        throw new Error('Network error did not trigger artifact_chunk_cancel');
      }}

      const errorReply = postedToNative.find(m => m.requestId === 'req-download-err');
      if (!errorReply || errorReply.ok !== false || errorReply.error.code !== 'NETWORK_ERROR') {{
        throw new Error('Network error frame missing or invalid: ' + JSON.stringify(errorReply));
      }}

      console.log(JSON.stringify({{ success: true }}));
    }}

    runTests().catch(err => {{
      console.error(err);
      process.exit(1);
    }});
    """

    res = subprocess.run(
        ["node", "-e", js_test_script],
        capture_output=True,
        text=True,
        timeout=15,
    )
    assert res.returncode == 0, f"Node script failed with: {res.stderr}\n{res.stdout}"
    json_lines = [line.strip() for line in res.stdout.strip().splitlines() if line.strip().startswith("{")]
    assert len(json_lines) > 0, f"No JSON output line found in stdout:\n{res.stdout}"
    output = json.loads(json_lines[-1])
    assert output["success"] is True
