/**
 * service_worker.js — Manifest V3 background service worker
 * Bridges Chrome Native Messaging ↔ page-main.js (MAIN world) via content_script.js (ISOLATED world).
 *
 * Security invariants:
 *  - Zero chrome.cookies API calls anywhere in this file.
 *  - Zero logging of auth tokens, CSRF values, cookie names, or raw HTTP response headers.
 *  - Provisioned tabs are recycled after TAB_COOLDOWN_MS (60 s).
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const NATIVE_HOST_NAME = 'com.mcp.gemini.broker';
const NOTEBOOK_ORIGINS = [
  'https://notebook.google.com',
  'https://notebooklm.google.com',
];
const KEEP_ALIVE_ALARM = 'keepalive';
const KEEP_ALIVE_INTERVAL_MINUTES = 0.5; // 30 seconds
const TAB_COOLDOWN_MS = 60_000;          // 60 seconds
const WIZ_POLL_INTERVAL_MS = 500;
const WIZ_POLL_TIMEOUT_MS = 15_000;
const MAX_RPC_TIMEOUT_MS = 240_000;      // 240 seconds hard ceiling (M-03)

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------

/** @type {chrome.runtime.Port | null} */
let nativePort = null;

/** @type {number | null} */
let provisionedTabId = null;

/** @type {number} */
let tabCreatedAt = 0;

/** @type {number} */
let tabLastActiveAt = 0;

/** @type {string | null} */
let lastKnownAuthuser = null;

// Pending response callbacks keyed by requestId
/** @type {Map<string, {resolve: Function, reject: Function, timeoutId: number}>} */
const pendingRequests = new Map();

// ---------------------------------------------------------------------------
// Keep-alive alarm
// ---------------------------------------------------------------------------

chrome.alarms.onAlarm.addListener((alarm) => {
  if (alarm.name === KEEP_ALIVE_ALARM) {
    // Fire-and-forget: just touching ensureNativePort keeps the SW alive.
    ensureNativePort();
  }
});

chrome.runtime.onStartup.addListener(() => {
  ensureNativePort();
  chrome.alarms.create(KEEP_ALIVE_ALARM, {
    periodInMinutes: KEEP_ALIVE_INTERVAL_MINUTES,
  });
});

chrome.runtime.onInstalled.addListener(() => {
  ensureNativePort();
  chrome.alarms.create(KEEP_ALIVE_ALARM, {
    periodInMinutes: KEEP_ALIVE_INTERVAL_MINUTES,
  });
});

// ---------------------------------------------------------------------------
// Native Messaging
// ---------------------------------------------------------------------------

function ensureNativePort() {
  if (nativePort !== null) {
    return;
  }

  try {
    nativePort = chrome.runtime.connectNative(NATIVE_HOST_NAME);

    nativePort.onMessage.addListener((message) => {
      handleNativeMessage(message).catch((err) => {
        console.error('[service_worker] Unhandled message error:', err);
      });
    });

    nativePort.onDisconnect.addListener(() => {
      if (chrome.runtime.lastError) {
        console.error('[service_worker] Native host disconnected:', chrome.runtime.lastError.message);
      }
      nativePort = null;
      setTimeout(ensureNativePort, 1000);
    });
  } catch (err) {
    console.error('[service_worker] connectNative error:', err);
    nativePort = null;
    setTimeout(ensureNativePort, 2000);
  }
}

/**
 * Receives a command from the native host, orchestrates tab provisioning,
 * script injection, and round-trips the result back.
 *
 * @param {object} message  Command from native host. Expected shape:
 *   { command: 'batchexecute'|'query_stream'|'scotty_upload', requestId: string, payload: object }
 */
async function handleNativeMessage(message) {
  const { command, requestId, payload } = message ?? {};

  if (!command || !requestId) {
    return;
  }

  // Domain A/E: Native Messaging Heartbeat
  if (command === 'HEARTBEAT_PING' || command === 'ping') {
    sendToNative({
      requestId,
      command: 'HEARTBEAT_PONG',
      type: 'pong',
      ok: true,
      timestamp: Date.now(),
    });
    return;
  }

  // P-02: Scotty chunk streaming and resumable upload
  if (command === 'scotty_chunk') {
    try {
      const res = await handleScottyChunkSW(payload);
      sendToNative({ requestId, ...res });
    } catch (err) {
      sendToNative({
        requestId,
        ok: false,
        error: {
          code: 'UPLOAD_STREAM_ERROR',
          message: err instanceof Error ? err.message : String(err),
          retryable: true,
        },
      });
    }
    return;
  }

  if (command === 'scotty_upload') {
    let fileBytes;
    try {
      const binary = atob(payload.fileBase64);
      fileBytes = new Uint8Array(binary.length);
      for (let i = 0; i < binary.length; i++) {
        fileBytes[i] = binary.charCodeAt(i);
      }
    } catch (err) {
      sendToNative({
        requestId,
        ok: false,
        error: { code: 'DECODE_ERROR', message: 'Failed to decode file bytes.', retryable: false },
      });
      return;
    }
    try {
      const res = await executeResumableScottyUpload(
        payload.sourceId,
        payload.filename,
        payload.notebookId,
        fileBytes,
        payload.authuser ?? 0
      );
      sendToNative({ requestId, ...res });
    } catch (err) {
      sendToNative({
        requestId,
        ok: false,
        error: {
          code: 'UPLOAD_STREAM_ERROR',
          message: err instanceof Error ? err.message : String(err),
          retryable: true,
        },
      });
    }
    return;
  }

  console.log('[service_worker] handleNativeMessage start:', command, requestId);

  let tab;
  try {
    tab = await ensureNotebookTab();
    console.log('[service_worker] ensureNotebookTab resolved:', tab.id, tab.url);
  } catch (_e) {
    console.error('[service_worker] ensureNotebookTab error');
    sendToNative({
      requestId,
      ok: false,
      error: { code: 'TAB_ERROR', message: 'Could not provision notebook tab.', retryable: true },
    });
    return;
  }

  try {
    await injectScripts(tab.id);
    console.log('[service_worker] injectScripts complete for tab:', tab.id);
  } catch (err) {
    console.error('[service_worker] injectScripts failed:', err);
    sendToNative({
      requestId,
      ok: false,
      error: { code: 'INJECT_ERROR', message: 'Could not inject page script: ' + (err?.message || err), retryable: true },
    });
    return;
  }

  // Send command to the page via content_script relay.
  let result;
  try {
    console.log('[service_worker] sendCommandToPage sending:', requestId);
    result = await sendCommandToPage(tab.id, { command, requestId, payload });
    console.log('[service_worker] sendCommandToPage returned:', requestId, result?.ok);
  } catch (err) {
    console.error('[service_worker] sendCommandToPage threw:', requestId, err);
    sendToNative({
      requestId,
      ok: false,
      error: { code: 'DISPATCH_ERROR', message: err instanceof Error ? err.message : String(err), retryable: true },
    });
    return;
  }

  if (payload?.traceparent && result && typeof result === 'object' && !result.traceparent) {
    result.traceparent = payload.traceparent;
  }

  tabLastActiveAt = Date.now();
  sendToNative({ requestId, ...result });

  // Recycle provisioned tab if cooldown has elapsed.
  maybeRecycleTab(tab.id);
}

/**
 * Sends a message to the native host. Does NOT log the payload.
 * @param {object} msg
 */
function sendToNative(msg) {
  console.log('[service_worker] sendToNative called, requestId:', msg?.requestId, 'ok:', msg?.ok);
  if (nativePort) {
    try {
      nativePort.postMessage(msg);
      console.log('[service_worker] nativePort.postMessage succeeded');
    } catch (err) {
      console.error('[service_worker] nativePort.postMessage threw:', err);
      nativePort = null;
      setTimeout(ensureNativePort, 1000);
    }
  } else {
    console.error('[service_worker] sendToNative: nativePort is null!');
    ensureNativePort();
  }
}

// ---------------------------------------------------------------------------
// P-02: Scotty Session URL Resumability Caching & Offset Querying
// ---------------------------------------------------------------------------

function getSessionStorageKey(notebookId, sourceId) {
  return `scotty_session_${notebookId}_${sourceId}`;
}

/**
 * Queries active Scotty upload session to retrieve server-confirmed byte offset.
 *
 * @param {string} sessionUrl
 * @returns {Promise<{status: string, offset: number}>}
 */
async function queryScottySessionOffset(sessionUrl) {
  const response = await fetch(sessionUrl, {
    method: 'POST',
    credentials: 'include',
    headers: {
      'X-Goog-Upload-Command': 'query',
    },
  });

  const uploadStatus =
    response.headers.get('X-Goog-Upload-Status') ||
    response.headers.get('x-goog-upload-status') ||
    'active';

  const offsetHeader =
    response.headers.get('X-Goog-Upload-Offset') ||
    response.headers.get('x-goog-upload-offset') ||
    '0';

  const offset = parseInt(offsetHeader, 10);
  return { status: uploadStatus, offset: Number.isNaN(offset) ? 0 : offset };
}

/**
 * Hardened Scotty Upload Handler with Session URL Caching & Resumability.
 *
 * @param {string} sourceId
 * @param {string} filename
 * @param {string} notebookId
 * @param {Uint8Array} fileBytes
 * @param {number} [authuser]
 * @returns {Promise<{ok: true, sourceId: string} | {ok: false, error: {code: string, message: string, retryable: boolean}}>}
 */
async function executeResumableScottyUpload(sourceId, filename, notebookId, fileBytes, authuser = 0) {
  const sessionKey = getSessionStorageKey(notebookId, sourceId);
  let sessionUrl = null;
  let startOffset = 0;

  // 1. Check for cached session URL in chrome.storage.session
  try {
    const cached = typeof chrome !== 'undefined' && chrome.storage?.session
      ? await chrome.storage.session.get(sessionKey)
      : null;
    if (cached && cached[sessionKey]) {
      sessionUrl = cached[sessionKey];
      try {
        const queryRes = await queryScottySessionOffset(sessionUrl);
        if (queryRes.status === 'final') {
          if (typeof chrome !== 'undefined' && chrome.storage?.session) {
            await chrome.storage.session.remove(sessionKey);
          }
          return { ok: true, sourceId };
        }
        startOffset = queryRes.offset;
        console.log(`[scotty] Resuming upload for ${sourceId} from server offset: ${startOffset}`);
      } catch (err) {
        console.warn('[scotty] Cached session query failed, creating fresh session.', err);
        sessionUrl = null;
        startOffset = 0;
        if (typeof chrome !== 'undefined' && chrome.storage?.session) {
          await chrome.storage.session.remove(sessionKey);
        }
      }
    }
  } catch (err) {
    console.warn('[scotty] chrome.storage.session read error:', err);
    sessionUrl = null;
    startOffset = 0;
  }

  // 2. If no valid session URL, initiate upload intent
  if (!sessionUrl) {
    const uploadInitUrl =
      'https://notebook.google.com/upload/_/LabsTailwindUi/feeds/upload/create_session/interactive/media/?authuser=' +
      encodeURIComponent(String(authuser));

    try {
      const initResponse = await fetch(uploadInitUrl, {
        method: 'POST',
        credentials: 'include',
        headers: {
          'X-Goog-Upload-Command': 'start',
          'X-Goog-Upload-Header-Content-Length': String(fileBytes.byteLength),
          'X-Goog-Upload-Header-Content-Type': 'application/octet-stream',
          'X-Goog-Upload-Protocol': 'resumable',
          'X-Same-Domain': '1',
          'X-Goog-Authuser': String(authuser),
        },
        body: JSON.stringify({
          PROJECT_ID: notebookId,
          SOURCE_NAME: filename,
          SOURCE_ID: sourceId,
          sourceId,
          notebookId,
          filename,
        }),
      });

      sessionUrl =
        initResponse.headers.get('x-goog-upload-url') ||
        initResponse.headers.get('X-Goog-Upload-URL');

      if (!sessionUrl) {
        return {
          ok: false,
          error: {
            code: 'UPLOAD_INIT_ERROR',
            message: 'No upload session URL returned by Scotty.',
            retryable: true,
          },
        };
      }

      if (typeof chrome !== 'undefined' && chrome.storage?.session) {
        await chrome.storage.session.set({ [sessionKey]: sessionUrl });
      }
    } catch (err) {
      return {
        ok: false,
        error: {
          code: 'UPLOAD_INIT_ERROR',
          message: err instanceof Error ? err.message : 'Upload init failed.',
          retryable: true,
        },
      };
    }
  }

  // 3. Stream remaining bytes starting from confirmed offset
  try {
    const payloadBytes = startOffset > 0 ? fileBytes.slice(startOffset) : fileBytes;

    await fetch(sessionUrl, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'Content-Type': 'application/octet-stream',
        'X-Goog-Upload-Command': 'upload, finalize',
        'X-Goog-Upload-Offset': String(startOffset),
      },
      body: payloadBytes,
    });

    if (typeof chrome !== 'undefined' && chrome.storage?.session) {
      try {
        await chrome.storage.session.remove(sessionKey);
      } catch (_) {}
    }

    return { ok: true, sourceId };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'UPLOAD_STREAM_ERROR',
        message: err instanceof Error ? err.message : 'Upload stream failed.',
        retryable: true,
      },
    };
  }
}

const swChunkCollectors = new Map();

async function handleScottyChunkSW(payload) {
  const { sourceId, filename, notebookId, chunkIndex, totalChunks, isLastChunk, chunkData, authuser } = payload;
  if (!swChunkCollectors.has(sourceId)) {
    swChunkCollectors.set(sourceId, {
      chunks: new Array(totalChunks),
      received: 0,
      totalChunks,
      filename,
      notebookId,
    });
  }

  const collector = swChunkCollectors.get(sourceId);
  const binary = atob(chunkData);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) {
    bytes[i] = binary.charCodeAt(i);
  }
  collector.chunks[chunkIndex] = bytes;
  collector.received++;

  if (isLastChunk) {
    let totalLength = 0;
    for (const c of collector.chunks) {
      totalLength += c ? c.length : 0;
    }
    const fullBytes = new Uint8Array(totalLength);
    let offset = 0;
    for (const c of collector.chunks) {
      if (c) {
        fullBytes.set(c, offset);
        offset += c.length;
      }
    }
    swChunkCollectors.delete(sourceId);
    return await executeResumableScottyUpload(
      sourceId,
      collector.filename,
      collector.notebookId,
      fullBytes,
      authuser ?? 0
    );
  }

  return { ok: true, chunkIndex, sourceId };
}

// ---------------------------------------------------------------------------
// Tab provisioning
// ---------------------------------------------------------------------------

/**
 * Returns an existing notebook tab or creates a new pinned background one.
 * Polls for WIZ_global_data.SNlM0e for up to WIZ_POLL_TIMEOUT_MS.
 *
 * @returns {Promise<chrome.tabs.Tab>}
 */
async function ensureNotebookTab() {
  // Look for an existing user-owned or previously-provisioned tab.
  for (const origin of NOTEBOOK_ORIGINS) {
    const tabs = await chrome.tabs.query({ url: origin + '/*' });
    if (tabs.length > 0) {
      // Ensure existing tab is protected from discard (M-04)
      await chrome.tabs.update(tabs[0].id, { autoDiscardable: false }).catch(() => {});
      return tabs[0];
    }
  }

  // Create a new background tab.
  const tab = await chrome.tabs.create({
    url: 'https://notebook.google.com/',
    active: false,
    pinned: true,
  });

  // M-04 Proactive Defense
  await chrome.tabs.update(tab.id, { autoDiscardable: false }).catch(() => {});

  provisionedTabId = tab.id;
  tabCreatedAt = Date.now();
  tabLastActiveAt = Date.now();

  // Wait for the tab to finish loading then poll for WIZ_global_data.SNlM0e.
  await waitForTabComplete(tab.id);
  await pollForWizData(tab.id);

  return tab;
}

// M-04 Reactive Fail-Safe: Tab discard listener
chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (changeInfo.discarded === true && (tabId === provisionedTabId || pendingRequests.size > 0)) {
    console.warn(`[service_worker] Tab ${tabId} was discarded by Chrome. Draining pending requests.`);
    for (const [requestId, pending] of pendingRequests.entries()) {
      clearTimeout(pending.timeoutId);
      pending.reject({
        ok: false,
        error: {
          code: 'TAB_DISCARDED',
          message: 'Notebook tab was discarded by browser memory management. Please retry.',
          retryable: true,
        },
      });
    }
    pendingRequests.clear();
    if (tabId === provisionedTabId) {
      provisionedTabId = null;
      tabCreatedAt = 0;
    }
  }
});

/**
 * Resolves when the tab's status becomes 'complete', or rejects after timeout.
 * @param {number} tabId
 * @returns {Promise<void>}
 */
function waitForTabComplete(tabId) {
  return new Promise((resolve, reject) => {
    const timeout = setTimeout(() => {
      chrome.tabs.onUpdated.removeListener(listener);
      reject(new Error('Tab load timeout'));
    }, WIZ_POLL_TIMEOUT_MS);

    function listener(updatedTabId, changeInfo) {
      if (updatedTabId === tabId && changeInfo.status === 'complete') {
        clearTimeout(timeout);
        chrome.tabs.onUpdated.removeListener(listener);
        resolve();
      }
    }

    chrome.tabs.onUpdated.addListener(listener);
  });
}

/**
 * Polls the tab at WIZ_POLL_INTERVAL_MS until WIZ_global_data.SNlM0e is present.
 * @param {number} tabId
 * @returns {Promise<void>}
 */
function pollForWizData(tabId) {
  return new Promise((resolve, reject) => {
    const start = Date.now();

    async function attempt() {
      if (Date.now() - start > WIZ_POLL_TIMEOUT_MS) {
        reject(new Error('WIZ_global_data poll timeout'));
        return;
      }

      try {
        const results = await chrome.scripting.executeScript({
          target: { tabId },
          world: 'MAIN',
          func: () => {
            return typeof window.WIZ_global_data !== 'undefined' &&
              typeof window.WIZ_global_data.SNlM0e === 'string' &&
              window.WIZ_global_data.SNlM0e.length > 0;
          },
        });

        if (results?.[0]?.result === true) {
          resolve();
          return;
        }
      } catch (_e) {
        // Tab not ready yet; keep polling.
      }

      setTimeout(attempt, WIZ_POLL_INTERVAL_MS);
    }

    attempt();
  });
}

// ---------------------------------------------------------------------------
// In-tab script injection (both ISOLATED content_script and MAIN page-main)
// ---------------------------------------------------------------------------

/**
 * Injects content_script.js (ISOLATED world) and page-main.js (MAIN world) into tab.
 *
 * @param {number} tabId
 * @returns {Promise<void>}
 */
async function injectScripts(tabId) {
  try {
    await chrome.scripting.executeScript({
      target: { tabId },
      files: ['content_script.js'],
    });
  } catch (_e) {
    // Already injected or restricted frame
  }

  await chrome.scripting.executeScript({
    target: { tabId },
    files: ['page-main.js'],
    world: 'MAIN',
  });
}

// ---------------------------------------------------------------------------
// Page command relay
// ---------------------------------------------------------------------------

/**
 * Sends a command to page-main.js through the content_script bridge
 * and waits for the result.
 *
 * @param {number} tabId
 * @param {object} command
 * @returns {Promise<object>}
 */
function sendCommandToPage(tabId, command) {
  return new Promise((resolve, reject) => {
    let timeoutMs =
      typeof command?.payload?.timeout_seconds === 'number'
        ? command.payload.timeout_seconds * 1000
        : command?.command === 'query_stream'
        ? 240_000
        : WIZ_POLL_TIMEOUT_MS * 2;

    if (timeoutMs > MAX_RPC_TIMEOUT_MS) {
      timeoutMs = MAX_RPC_TIMEOUT_MS;
    }

    const timeoutId = setTimeout(() => {
      pendingRequests.delete(command.requestId);
      reject({
        ok: false,
        error: {
          code: 'RPC_EXECUTION_TIMEOUT',
          message: `RPC operation exceeded maximum MV3 safety ceiling of 240s (${timeoutMs}ms).`,
          retryable: true,
        },
      });
    }, timeoutMs);

    pendingRequests.set(command.requestId, { resolve, reject, timeoutId });

    chrome.tabs.sendMessage(tabId, {
      destination: 'page_main',
      ...command,
    }).catch((err) => {
      pendingRequests.delete(command.requestId);
      clearTimeout(timeoutId);
      reject(err);
    });
  });
}

// ---------------------------------------------------------------------------
// Messages from content_script
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || !message.type) {
    return false;
  }

  if (message.type === 'content_script_ready') {
    ensureNativePort();
    sendResponse({ ok: true, connected: nativePort !== null });
    return false;
  }

  if (message.type === 'page_ready') {
    ensureNativePort();
    // Tab has WIZ_global_data populated; store routing hint (index only, not token).
    if (typeof message.authuser === 'number') {
      lastKnownAuthuser = String(message.authuser);
    }
    sendResponse({ ok: true, connected: nativePort !== null });
    return false;
  }

  if (message.type === 'page_result') {
    const { requestId, result } = message;
    console.log('[service_worker] onMessage page_result:', requestId, result?.ok);
    const pending = pendingRequests.get(requestId);
    if (pending) {
      clearTimeout(pending.timeoutId);
      pendingRequests.delete(requestId);
      pending.resolve(result ?? { ok: false, error: { code: 'EMPTY_RESULT', message: 'No result.', retryable: false } });
    } else {
      console.warn('[service_worker] No pending request for requestId:', requestId);
    }

    // Try to recycle the provisioned tab (tab id comes from sender).
    const senderTabId = _sender?.tab?.id;
    if (senderTabId != null) {
      maybeRecycleTab(senderTabId);
    }

    sendResponse({ ok: true });
    return false;
  }

  if (message.type === 'get_status') {
    sendResponse({
      ok: true,
      connected: nativePort !== null,
      authuser: lastKnownAuthuser,
    });
    return false;
  }

  if (message.type === 'initiate_pairing') {
    ensureNativePort();
    sendResponse({ ok: true, connected: nativePort !== null });
    return false;
  }

  return false;
});

// ---------------------------------------------------------------------------
// Tab recycling
// ---------------------------------------------------------------------------

/**
 * Removes a provisioned tab if it was created by the extension and the
 * cooldown period has elapsed.
 *
 * @param {number} tabId
 */
function maybeRecycleTab(tabId) {
  if (
    tabId === provisionedTabId &&
    provisionedTabId !== null &&
    pendingRequests.size === 0 &&
    Date.now() - tabLastActiveAt > TAB_COOLDOWN_MS
  ) {
    chrome.tabs.remove(provisionedTabId).catch(() => {});
    provisionedTabId = null;
    tabCreatedAt = 0;
  }
}

// Automatically attempt native port connection on service worker startup.
ensureNativePort();

globalThis.__mcp_getStatus = () => ({
  connected: nativePort !== null,
  pending: Array.from(pendingRequests.keys()),
  provisionedTab: provisionedTabId,
});
globalThis.__mcp_ensureNativePort = ensureNativePort;
globalThis.ensureNativePort = ensureNativePort;
globalThis.getSessionStorageKey = getSessionStorageKey;
globalThis.queryScottySessionOffset = queryScottySessionOffset;
globalThis.executeResumableScottyUpload = executeResumableScottyUpload;
globalThis.handleScottyChunkSW = handleScottyChunkSW;

