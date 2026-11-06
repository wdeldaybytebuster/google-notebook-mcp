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

/** @type {string | null} */
let lastNativeError = null;

// Pending response callbacks keyed by requestId (SW -> page-main.js)
/** @type {Map<string, {resolve: Function, reject: Function, timeoutId: number}>} */
const pendingRequests = new Map();

// Pending broker command callbacks keyed by requestId (SW -> native_host.py -> BrokerDaemon)
/** @type {Map<string, {resolve: Function, reject: Function, timeoutId: number}>} */
const pendingBrokerRequests = new Map();

/** @type {number} */
let brokerRequestSeq = 0;

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
      lastNativeError = null;
      handleNativeMessage(message).catch((err) => {
        console.error('[service_worker] Unhandled message error:', err);
      });
    });

    nativePort.onDisconnect.addListener(() => {
      const errMsg = chrome.runtime?.lastError?.message || 'Native host disconnected.';
      lastNativeError = errMsg;
      if (chrome.runtime?.lastError) {
        console.error('[service_worker] Native host disconnected:', errMsg);
      }
      for (const [, pending] of pendingBrokerRequests.entries()) {
        clearTimeout(pending.timeoutId);
        pending.reject(new Error(errMsg));
      }
      pendingBrokerRequests.clear();
      nativePort = null;
      setTimeout(ensureNativePort, 1000);
    });
  } catch (err) {
    lastNativeError = err instanceof Error ? err.message : String(err);
    console.error('[service_worker] connectNative error:', err);
    nativePort = null;
    setTimeout(ensureNativePort, 2000);
  }
}

/**
 * Sends an administrative/WebUI command directly to the Python BrokerDaemon over nativePort
 * and awaits the correlated reply by requestId.
 *
 * @param {string} action
 * @param {object} [payload]
 * @param {number} [timeoutMs]
 * @returns {Promise<object>}
 */
function sendBrokerCommand(action, payload = {}, timeoutMs = 15_000) {
  ensureNativePort();
  if (!nativePort) {
    return Promise.reject(new Error(lastNativeError || 'Native host is disconnected.'));
  }

  const requestId = `sw-${Date.now()}-${++brokerRequestSeq}`;
  return new Promise((resolve, reject) => {
    const timeoutId = setTimeout(() => {
      pendingBrokerRequests.delete(requestId);
      reject(new Error(`Broker command '${action}' timed out after ${timeoutMs}ms.`));
    }, timeoutMs);

    pendingBrokerRequests.set(requestId, { resolve, reject, timeoutId });

    try {
      nativePort.postMessage({
        action,
        ...payload,
        requestId,
      });
    } catch (err) {
      clearTimeout(timeoutId);
      pendingBrokerRequests.delete(requestId);
      nativePort = null;
      setTimeout(ensureNativePort, 1000);
      reject(err);
    }
  });
}

/**
 * Receives a command from the native host, orchestrates tab provisioning,
 * script injection, and round-trips the result back.
 *
 * @param {object} message  Command from native host. Expected shape:
 *   { command: 'batchexecute'|'query_stream'|'scotty_upload', requestId: string, payload: object }
 */
async function handleNativeMessage(message) {
  if (message?.requestId && pendingBrokerRequests.has(message.requestId)) {
    const pendingBroker = pendingBrokerRequests.get(message.requestId);
    clearTimeout(pendingBroker.timeoutId);
    pendingBrokerRequests.delete(message.requestId);
    pendingBroker.resolve(message);
    return;
  }

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

  // Route Scotty uploads via page-main.js (MAIN world) when tab injection APIs are available
  // so verifyAccountIdentityPreflight (P-03) is strictly enforced before uploading bytes.
  // Retain SW fallback only for isolated unit-test environments without tab injection mocks.
  const canRouteViaTab =
    typeof chrome !== 'undefined' &&
    typeof chrome.tabs?.query === 'function' &&
    typeof chrome.scripting?.executeScript === 'function';

  // P-02: Scotty chunk streaming and resumable upload fallback (unit test mocks)
  if (!canRouteViaTab && command === 'scotty_chunk') {
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

  if (!canRouteViaTab && command === 'scotty_upload') {
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

  // Phase 10: Studio Artifact Retrieval Engine binary streaming
  if (command === 'download_artifact') {
    handleDownloadArtifact(requestId, payload).catch((err) => {
      sendToNative({
        requestId,
        ok: false,
        error: {
          code: 'DOWNLOAD_ERROR',
          message: err instanceof Error ? err.message : String(err),
          retryable: true,
        },
      });
    });
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
      extensionId: chrome.runtime?.id || '',
      lastError: lastNativeError,
    });
    return false;
  }

  if (message.type === 'initiate_pairing') {
    ensureNativePort();
    sendResponse({ ok: true, connected: nativePort !== null });
    return false;
  }

  if (message.type === 'get_allowlist') {
    (async () => {
      try {
        const res = await sendBrokerCommand('get_allowlist', {});
        if (res?.ok && res.notebooks && chrome.storage?.local) {
          await chrome.storage.local.set({ allowlisted_notebooks: res.notebooks });
        }
        sendResponse(res);
      } catch (err) {
        try {
          const cached = chrome.storage?.local
            ? await chrome.storage.local.get('allowlisted_notebooks')
            : {};
          sendResponse({
            ok: true,
            notebooks: cached?.allowlisted_notebooks || {},
            offline: true,
          });
        } catch (_storageErr) {
          sendResponse({
            ok: false,
            error: {
              code: 'NATIVE_DISCONNECTED',
              message: err instanceof Error ? err.message : String(err),
            },
          });
        }
      }
    })();
    return true;
  }

  if (message.type === 'discover_notebooks') {
    (async () => {
      try {
        const res = await sendBrokerCommand('discover_notebooks', {});
        if (res?.ok && Array.isArray(res.notebooks)) {
          if (chrome.storage?.local) {
            await chrome.storage.local.set({ discovered_notebooks: res.notebooks });
          }
          sendResponse({ ok: true, notebooks: res.notebooks });
          return;
        }
        sendResponse(res);
      } catch (err) {
        // Fallback: if broker is disconnected or busy, attempt direct wXbhsf discovery on hydrated tab
        try {
          if (
            typeof chrome.tabs?.query === 'function' &&
            typeof chrome.scripting?.executeScript === 'function'
          ) {
            const tab = await ensureNotebookTab();
            await injectScripts(tab.id);
            const fallbackReqId = `sw-disc-${Date.now()}`;
            const pageRes = await sendCommandToPage(tab.id, {
              command: 'batchexecute',
              requestId: fallbackReqId,
              payload: { rpcId: 'wXbhsf', paramsJson: '[null,1,null,[2]]' },
            });
            const notebooks = parseWxbhsfNotebooksFallback(pageRes?.body || '');
            if (chrome.storage?.local) {
              await chrome.storage.local.set({ discovered_notebooks: notebooks });
            }
            sendResponse({ ok: true, notebooks });
            return;
          }
        } catch (_fallbackErr) {
          // Ignore fallback error and return primary error envelope
        }
        sendResponse({
          ok: false,
          error: {
            code: 'DISCOVERY_FAILED',
            message: err instanceof Error ? err.message : String(err),
          },
        });
      }
    })();
    return true;
  }

  if (message.type === 'update_allowlist') {
    (async () => {
      try {
        const res = await sendBrokerCommand('update_allowlist', {
          notebooks: message.notebooks || {},
          validate_uuids: Boolean(message.validate_uuids),
        });
        if (res?.ok && res.notebooks && chrome.storage?.local) {
          await chrome.storage.local.set({ allowlisted_notebooks: res.notebooks });
        }
        sendResponse(res);
      } catch (err) {
        sendResponse({
          ok: false,
          error: {
            code: 'ALLOWLIST_SYNC_FAILED',
            message: err instanceof Error ? err.message : String(err),
          },
        });
      }
    })();
    return true;
  }

  return false;
});

/**
 * Lightweight fallback parser for raw wXbhsf batchexecute body when queried directly from SW.
 * Extracts [title, ..., notebookId] rows safely without logging response contents.
 *
 * @param {string} rawBody
 * @returns {Array<{id: string, title: string, allowed: boolean, mode: string}>}
 */
function parseWxbhsfNotebooksFallback(rawBody) {
  if (typeof rawBody !== 'string' || !rawBody) {
    return [];
  }
  const results = [];
  const lines = rawBody.replace(/^\)\]\}'\s*/, '').split('\n');
  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed.startsWith('[')) continue;
    try {
      const parsed = JSON.parse(trimmed);
      if (!Array.isArray(parsed)) continue;
      for (const item of parsed) {
        if (Array.isArray(item) && item[0] === 'wrb.fr' && item[1] === 'wXbhsf' && typeof item[2] === 'string') {
          const inner = JSON.parse(item[2]);
          const rows = Array.isArray(inner?.[0]) ? inner[0] : inner;
          if (!Array.isArray(rows)) continue;
          for (const row of rows) {
            if (!Array.isArray(row)) continue;
            // NotebookLM wXbhsf row layout: [title, sources, uuid, ...] or [uuid, title, ...]
            let id = '';
            let title = 'Untitled Notebook';
            if (typeof row[2] === 'string' && row[2].includes('-')) {
              id = row[2];
              if (typeof row[0] === 'string' && row[0]) title = row[0];
            } else if (typeof row[0] === 'string') {
              id = row[0];
              if (typeof row[1] === 'string' && row[1]) title = row[1];
            }
            if (id) {
              results.push({ id, title, allowed: false, mode: 'READ_ONLY' });
            }
          }
        }
      }
    } catch (_e) {
      // Ignore non-JSON length lines in chunked batchexecute wire format
    }
  }
  return results;
}

// ---------------------------------------------------------------------------
// Phase 10: Studio Artifact Retrieval Engine Stream Interception
// ---------------------------------------------------------------------------

/**
 * Safely converts a Uint8Array slice to Base64 without call-stack overflow.
 * @param {Uint8Array} bytes
 * @returns {string}
 */
function uint8ArrayToBase64(bytes) {
  if (!bytes || bytes.length === 0) {
    return '';
  }
  const BLOCK_SIZE = 32768;
  let binary = '';
  for (let i = 0; i < bytes.length; i += BLOCK_SIZE) {
    const chunk = bytes.subarray(i, i + BLOCK_SIZE);
    binary += String.fromCharCode.apply(null, chunk);
  }
  return btoa(binary);
}

/**
 * Downloads a Studio binary artifact with stream slicing, safe Base64 encoding,
 * and ACK-based backpressure flow control to the native host / broker.
 *
 * @param {string} requestId
 * @param {object} payload
 */
async function handleDownloadArtifact(requestId, payload) {
  const url = payload?.url || payload?.downloadUrl || payload?.download_url;
  const artifactId = payload?.artifactId || payload?.artifact_id;
  const sessionId = payload?.sessionId || payload?.session_id;
  const artifactType = payload?.artifactType || payload?.artifact_type || 'AUDIO';

  if (!url) {
    sendToNative({
      requestId,
      ok: false,
      error: { code: 'INVALID_URL', message: 'No artifact download URL provided.', retryable: false },
    });
    return;
  }

  const CHUNK_SIZE = 524288; // <= 512 KiB (524,288 bytes)
  let response;
  try {
    response = await fetch(url, {
      method: 'GET',
      credentials: 'include',
    });
  } catch (err) {
    try {
      await sendBrokerCommand('artifact_chunk_cancel', {
        artifactId,
        sessionId,
        reason: err instanceof Error ? err.message : String(err),
      });
    } catch (_e) {}
    sendToNative({
      requestId,
      ok: false,
      error: {
        code: 'NETWORK_ERROR',
        message: `Failed to fetch artifact: ${err instanceof Error ? err.message : String(err)}`,
        retryable: true,
      },
    });
    return;
  }

  if (!response.ok) {
    try {
      await sendBrokerCommand('artifact_chunk_cancel', {
        artifactId,
        sessionId,
        reason: `HTTP ${response.status}`,
      });
    } catch (_e) {}
    sendToNative({
      requestId,
      ok: false,
      error: {
        code: 'HTTP_ERROR',
        message: `Artifact download failed with status ${response.status} ${response.statusText}`,
        retryable: response.status >= 500,
      },
    });
    return;
  }

  if (!response.body) {
    sendToNative({
      requestId,
      ok: false,
      error: { code: 'EMPTY_BODY', message: 'Response body is empty.', retryable: false },
    });
    return;
  }

  const reader = response.body.getReader();
  let buffer = new Uint8Array(0);
  let chunkIndex = 0;
  let totalBytes = 0;

  try {
    while (true) {
      const { done, value } = await reader.read();

      if (value && value.length > 0) {
        const newBuf = new Uint8Array(buffer.length + value.length);
        newBuf.set(buffer, 0);
        newBuf.set(value, buffer.length);
        buffer = newBuf;
      }

      // Flush full CHUNK_SIZE slices
      while (buffer.length >= CHUNK_SIZE && !done) {
        const slice = buffer.subarray(0, CHUNK_SIZE);
        buffer = buffer.subarray(CHUNK_SIZE);
        totalBytes += slice.length;

        const base64Str = uint8ArrayToBase64(slice);
        const ack = await sendBrokerCommand('artifact_chunk', {
          artifactId,
          sessionId,
          chunkIndex: chunkIndex++,
          chunkBase64: base64Str,
          artifactType,
          isLast: false,
        });

        if (!ack || !ack.ok) {
          throw new Error(ack?.error?.message || 'Broker rejected artifact chunk.');
        }
      }

      if (done) {
        while (buffer.length > CHUNK_SIZE) {
          const slice = buffer.subarray(0, CHUNK_SIZE);
          buffer = buffer.subarray(CHUNK_SIZE);
          totalBytes += slice.length;
          const base64Str = uint8ArrayToBase64(slice);
          const ack = await sendBrokerCommand('artifact_chunk', {
            artifactId,
            sessionId,
            chunkIndex: chunkIndex++,
            chunkBase64: base64Str,
            artifactType,
            isLast: false,
          });
          if (!ack || !ack.ok) {
            throw new Error(ack?.error?.message || 'Broker rejected artifact chunk.');
          }
        }

        totalBytes += buffer.length;
        const lastBase64 = uint8ArrayToBase64(buffer);
        const finalAck = await sendBrokerCommand('artifact_chunk', {
          artifactId,
          sessionId,
          chunkIndex: chunkIndex++,
          chunkBase64: lastBase64,
          artifactType,
          isLast: true,
        });

        if (!finalAck || !finalAck.ok) {
          throw new Error(finalAck?.error?.message || 'Broker failed to commit final artifact chunk.');
        }

        sendToNative({
          requestId,
          ok: true,
          artifactId,
          sessionId,
          totalBytes,
          filePath: finalAck.file_path || finalAck.filePath,
        });
        return;
      }
    }
  } catch (err) {
    try {
      await reader.cancel();
    } catch (_e) {}
    try {
      await sendBrokerCommand('artifact_chunk_cancel', {
        artifactId,
        sessionId,
        reason: err instanceof Error ? err.message : String(err),
      });
    } catch (_e) {}

    sendToNative({
      requestId,
      ok: false,
      error: {
        code: 'STREAM_ERROR',
        message: `Artifact stream error: ${err instanceof Error ? err.message : String(err)}`,
        retryable: true,
      },
    });
  }
}

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
globalThis.uint8ArrayToBase64 = uint8ArrayToBase64;
globalThis.handleDownloadArtifact = handleDownloadArtifact;

