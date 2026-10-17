/**
 * content_script.js — Runs in ISOLATED world on notebook.google.com / notebooklm.google.com
 *
 * Security invariants:
 *  - This script cannot access window.WIZ_global_data (wrong world — that requires MAIN world).
 *  - It only relays opaque message envelopes between service_worker.js and page-main.js.
 *  - Zero logging of auth values, cookie names, or raw HTTP response headers.
 */

// ---------------------------------------------------------------------------
// DOMContentLoaded — signal readiness to service_worker
// ---------------------------------------------------------------------------

if (window.__mcp_content_script_active) {
  // Already active in this isolated world context
} else {
  window.__mcp_content_script_active = true;

  function signalReady() {
    chrome.runtime.sendMessage({
      type: 'content_script_ready',
      url: location.href,
    }).catch(() => {
      // Service worker may not be ready yet; silently drop.
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', signalReady);
  } else {
    signalReady();
  }

// ---------------------------------------------------------------------------
// window.addEventListener — relay page-main.js results to service_worker
// ---------------------------------------------------------------------------

window.addEventListener('message', (event) => {
  // Only accept messages from our own page context.
  if (event.source !== window) {
    return;
  }

  const msg = event.data;
  if (!msg || msg.source !== 'page_main_result') {
    return;
  }

  // 'ready' signals from page-main are informational; translate to page_ready.
  if (msg.type === 'ready') {
    chrome.runtime.sendMessage({
      type: 'page_ready',
      // authuser index only — no tokens or CSRF values are passed.
      authuser: typeof msg.authuser === 'number' ? msg.authuser : 0,
    }).catch(() => {});
    return;
  }

  // Forward result envelope back to service_worker.
  if (msg.requestId) {
    chrome.runtime.sendMessage({
      type: 'page_result',
      requestId: msg.requestId,
      result: msg.result,
    }).catch(() => {});
  }
});

// ---------------------------------------------------------------------------
// chrome.runtime.onMessage — relay commands from service_worker to page-main
// ---------------------------------------------------------------------------

chrome.runtime.onMessage.addListener((message, _sender, sendResponse) => {
  if (!message || message.destination !== 'page_main') {
    return false;
  }

  // Forward command into MAIN world via window.postMessage.
  window.postMessage(
    {
      source: 'mcp_bridge_cmd',
      command: message.command,
      requestId: message.requestId,
      payload: message.payload,
    },
    '*'
  );

  sendResponse({ ok: true });
  return false;
});
}
