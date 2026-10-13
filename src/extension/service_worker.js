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

// ---------------------------------------------------------------------------
// Module-level state
// ---------------------------------------------------------------------------

/** @type {chrome.runtime.Port | null} */
let nativePort = null;

/** @type {number | null} */
let provisionedTabId = null;

/** @type {number} */
let tabCreatedAt = 0;

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
  chrome.alarms.create(KEEP_ALIVE_ALARM, {
    periodInMinutes: KEEP_ALIVE_INTERVAL_MINUTES,
  });
});

chrome.runtime.onInstalled.addListener(() => {
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
      handleNativeMessage(message).catch(() => {
        // Error already handled inside; silently absorb to avoid SW crash.
      });
    });

    nativePort.onDisconnect.addListener(() => {
      nativePort = null;
      // chrome.runtime.lastError consumed to suppress unchecked error warnings.
      void chrome.runtime.lastError;
    });
  } catch (_e) {
    nativePort = null;
  }
}

/**
 * Receives a command from the native host, orchestrates tab provisioning,
 * page-main.js injection, and round-trips the result back.
 *
 * @param {object} message  Command from native host. Expected shape:
 *   { command: 'batchexecute'|'query_stream'|'scotty_upload', requestId: string, payload: object }
 */
async function handleNativeMessage(message) {
  const { command, requestId, payload } = message ?? {};

  if (!command || !requestId) {
    return;
  }

  let tab;
  try {
    tab = await ensureNotebookTab();
  } catch (_e) {
    sendToNative({
      requestId,
      ok: false,
      error: { code: 'TAB_ERROR', message: 'Could not provision notebook tab.', retryable: true },
    });
    return;
  }

  try {
    await injectPageMain(tab.id);
  } catch (_e) {
    sendToNative({
      requestId,
      ok: false,
      error: { code: 'INJECT_ERROR', message: 'Could not inject page script.', retryable: true },
    });
    return;
  }

  // Send command to the page via content_script relay.
  const result = await sendCommandToPage(tab.id, { command, requestId, payload });

  sendToNative({ requestId, ...result });

  // Recycle provisioned tab if cooldown has elapsed.
  maybeRecycleTab(tab.id);
}

/**
 * Sends a message to the native host. Does NOT log the payload.
 * @param {object} msg
 */
function sendToNative(msg) {
  if (nativePort) {
    try {
      nativePort.postMessage(msg);
    } catch (_e) {
      nativePort = null;
    }
  }
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
      return tabs[0];
    }
  }

  // Create a new background tab.
  const tab = await chrome.tabs.create({
    url: 'https://notebook.google.com/',
    active: false,
    pinned: true,
  });

  provisionedTabId = tab.id;
  tabCreatedAt = Date.now();

  // Wait for the tab to finish loading then poll for WIZ_global_data.SNlM0e.
  await waitForTabComplete(tab.id);
  await pollForWizData(tab.id);

  return tab;
}

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
// Page-main injection
// ---------------------------------------------------------------------------

/**
 * Injects page-main.js into the MAIN world of the given tab.
 * This gives the script access to window.WIZ_global_data.
 *
 * @param {number} tabId
 * @returns {Promise<void>}
 */
async function injectPageMain(tabId) {
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
    const timeoutId = setTimeout(() => {
      pendingRequests.delete(command.requestId);
      reject(new Error('Page command timeout'));
    }, WIZ_POLL_TIMEOUT_MS * 2);

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
    // No-op: acknowledge tab is alive.
    sendResponse({ ok: true });
    return false;
  }

  if (message.type === 'page_ready') {
    // Tab has WIZ_global_data populated; store routing hint (index only, not token).
    if (typeof message.authuser === 'number') {
      lastKnownAuthuser = String(message.authuser);
    }
    sendResponse({ ok: true });
    return false;
  }

  if (message.type === 'page_result') {
    const { requestId, result } = message;
    const pending = pendingRequests.get(requestId);
    if (pending) {
      clearTimeout(pending.timeoutId);
      pendingRequests.delete(requestId);
      pending.resolve(result ?? { ok: false, error: { code: 'EMPTY_RESULT', message: 'No result.', retryable: false } });
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
    Date.now() - tabCreatedAt > TAB_COOLDOWN_MS
  ) {
    chrome.tabs.remove(provisionedTabId).catch(() => {});
    provisionedTabId = null;
    tabCreatedAt = 0;
  }
}

// Automatically attempt native port connection on service worker startup.
ensureNativePort();
