/**
 * page-main.js — Injected into the MAIN world via chrome.scripting.executeScript.
 *
 * Running in the MAIN world gives this script access to window.WIZ_global_data,
 * which contains page-resident CSRF and session identifiers used to construct
 * authenticated fetch() calls. These values NEVER appear in postMessage results
 * returned to content_script.js or the service worker.
 *
 * Security invariants:
 *  - SNlM0e, FdrFJe, cookie values, ya29 tokens, and raw HTTP response headers
 *    MUST NOT appear in any postMessage result or console output.
 *  - Auth context is consumed locally within each function call only.
 *  - Zero console.log / console.error calls that reference token values.
 */

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

if (window.__mcp_page_main_active) {
  // Already active in this MAIN world context
} else {
  window.__mcp_page_main_active = true;

const BATCHEXECUTE_URL =
  'https://notebook.google.com/_/LabsTailwindUi/data/batchexecute';
const QUERY_URL =
  'https://notebook.google.com/_/LabsTailwindUi/data/google.internal.labs.tailwind.orchestration.v1.LabsTailwindOrchestrationService/GenerateFreeFormStreamed';

// ---------------------------------------------------------------------------
// Auth context — values remain in page scope, never forwarded
// ---------------------------------------------------------------------------

/**
 * Reads page-resident auth identifiers from WIZ_global_data.
 * The returned object stays inside page-main.js; it is NEVER posted back
 * to content_script or the service worker.
 *
 * @returns {{ snlm0e: string, fdrfje: string, authuser: number, accountEmail: string }}
 */
function getAuthContext() {
  const wiz = window.WIZ_global_data ?? {};

  const snlm0e = typeof wiz.SNlM0e === 'string' ? wiz.SNlM0e : '';
  const fdrfje = typeof wiz.FdrFJe === 'string' ? wiz.FdrFJe : '';
  const accountEmail = (
    (typeof wiz.oPEP7c === 'string' && wiz.oPEP7c.includes('@') ? wiz.oPEP7c : '') ||
    (typeof wiz.oM1Kwf === 'string' && wiz.oM1Kwf.includes('@') ? wiz.oM1Kwf : '') ||
    Object.values(wiz).find((v) => typeof v === 'string' && v.includes('@') && v.includes('.')) ||
    ''
  ).trim().toLowerCase();

  // Extract /u/{N}/ from the current pathname; default to 0.
  const match = window.location.pathname.match(/\/u\/(\d+)\//);
  const authuser = match ? parseInt(match[1], 10) : 0;

  return Object.freeze({ snlm0e, fdrfje, authuser, accountEmail });
}

// ---------------------------------------------------------------------------
// M-09: Safe Request Body Inspection (Zero Stream Consumption)
// ---------------------------------------------------------------------------

function inspectRequestBodySafely(body) {
  if (typeof body === 'string') {
    return body;
  }
  if (body instanceof URLSearchParams) {
    return body.toString();
  }
  // CRITICAL: NEVER touch ReadableStream or FormData streams to prevent bodyUsed = true
  return null;
}

// ---------------------------------------------------------------------------
// P-03: Pre-flight Account Identity Guard on Mutations
// ---------------------------------------------------------------------------

const MUTATING_COMMANDS = new Set([
  'add_source',
  'create_note',
  'delete_note',
  'scotty_upload',
  'scotty_chunk',
]);

const MUTATING_RPC_IDS = new Set([
  'izAoDd', // Ingest text / url / drive source
  'CYK0Xb', // Create user note
  'tGMBJ',  // Delete user note
  'o4cbdc', // Register Scotty file upload
]);

/**
 * Validates active Google account identity before initiating mutations.
 * Prevents unauthorized writes to incorrect accounts in multi-account Chrome profiles.
 *
 * @param {string} command
 * @param {object} payload
 * @returns {{ok: true} | {ok: false, error: object}}
 */
function verifyAccountIdentityPreflight(command, payload) {
  const isMutating =
    MUTATING_COMMANDS.has(command) ||
    (command === 'batchexecute' && MUTATING_RPC_IDS.has(payload?.rpcId));

  if (!isMutating) {
    return { ok: true };
  }

  const wiz = window.WIZ_global_data ?? {};
  const activeEmail = (
    (typeof wiz.oPEP7c === 'string' && wiz.oPEP7c.includes('@') ? wiz.oPEP7c : '') ||
    (typeof wiz.oM1Kwf === 'string' && wiz.oM1Kwf.includes('@') ? wiz.oM1Kwf : '') ||
    Object.values(wiz).find((v) => typeof v === 'string' && v.includes('@') && v.includes('.')) ||
    ''
  ).trim().toLowerCase();

  // If no account is logged in, fail immediately
  if (!activeEmail) {
    return {
      ok: false,
      error: {
        code: 'AUTH_REQUIRED',
        message: 'No active Google account identity detected in window.WIZ_global_data.',
        retryable: false,
      },
    };
  }

  // 1. Verify specific expected email
  if (payload?.expectedEmail) {
    const expected = String(payload.expectedEmail).trim().toLowerCase();
    if (activeEmail !== expected) {
      return {
        ok: false,
        error: {
          code: 'PERMISSION_DENIED',
          message: `Active Google account (${activeEmail}) does not match expectedEmail (${expected}).`,
          retryable: false,
        },
      };
    }
  }

  // 2. Verify account against allowed list
  if (Array.isArray(payload?.expectedAccounts) && payload.expectedAccounts.length > 0) {
    const allowed = new Set(payload.expectedAccounts.map((a) => String(a).trim().toLowerCase()));
    if (!allowed.has(activeEmail)) {
      return {
        ok: false,
        error: {
          code: 'PERMISSION_DENIED',
          message: `Active Google account (${activeEmail}) does not match allowlist.`,
          retryable: false,
        },
      };
    }
  }

  return { ok: true };
}

// ---------------------------------------------------------------------------
// batchexecute
// ---------------------------------------------------------------------------

/**
 * Executes a batchexecute RPC via in-browser fetch().
 * The CSRF token (snlm0e) is used to construct the form body but is
 * NEVER included in the returned result object.
 *
 * @param {string} rpcId
 * @param {string} paramsJson
 * @param {string | null} notebookId
 * @returns {Promise<{ok: true, body: string} | {ok: false, error: {code: string, message: string, retryable: boolean}}>}
 */
async function executeBatchexecute(rpcId, paramsJson, notebookId, traceparent = null) {
  const auth = getAuthContext();
  if (!auth.snlm0e) {
    return {
      ok: false,
      error: {
        code: 'CSRF_MISSING',
        message: 'CSRF token (SNlM0e) not available on page.',
        retryable: true,
      },
    };
  }

  // Build the URL; append authuser only when it is non-zero.
  let url = BATCHEXECUTE_URL;
  const urlParams = new URLSearchParams();
  if (auth.authuser > 0) {
    urlParams.set('authuser', String(auth.authuser));
  }
  if (notebookId) {
    urlParams.set('source-path', `/notebook/${notebookId}`);
  }
  const wiz = window.WIZ_global_data ?? {};
  if (wiz.cfb2h) {
    urlParams.set('bl', String(wiz.cfb2h));
  }
  if (wiz.FdrFJe) {
    urlParams.set('f.sid', String(wiz.FdrFJe));
  }
  urlParams.set('rt', 'c');
  const qs = urlParams.toString();
  if (qs) {
    url = url + '?' + qs;
  }

  // Build form body. The at= field carries snlm0e (CSRF); it is consumed here only.
  const body = new URLSearchParams();
  body.set('f.req', JSON.stringify([[[rpcId, paramsJson, null, 'generic']]]));
  body.set('at', auth.snlm0e);

  try {
    const headers = {
      'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
      'X-Same-Domain': '1',
    };
    if (traceparent) {
      headers['traceparent'] = traceparent;
    }
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: body.toString(),
    });

    if (response.status === 400) {
      return {
        ok: false,
        error: {
          code: 'UPSTREAM_SCHEMA_DRIFT',
          message: 'Upstream returned HTTP 400 Bad Request (schema drift detected).',
          retryable: false,
        },
      };
    }

    const text = await response.text();

    // Strip anti-XSSI prefix.
    const stripped = text.startsWith(')]}\'\\n')
      ? text.slice(5)
      : text.startsWith(')]}\'')
      ? text.slice(4)
      : text;

    return { ok: true, body: stripped };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'FETCH_ERROR',
        message: err instanceof Error ? err.message : 'Unknown fetch error',
        retryable: true,
      },
    };
  }
}

// ---------------------------------------------------------------------------
// query_stream
// ---------------------------------------------------------------------------

/**
 * Submits a query to the streaming GenerateFreeFormStreamed endpoint.
 * Reads the full streamed response body before returning.
 * Auth values are consumed locally; they do not appear in the result.
 *
 * @param {string} paramsJson
 * @returns {Promise<{ok: true, body: string} | {ok: false, error: {code: string, message: string, retryable: boolean}}>}
 */
async function executeQueryStream(paramsJson, traceparent = null) {
  const auth = getAuthContext();
  if (!auth.snlm0e) {
    return {
      ok: false,
      error: {
        code: 'CSRF_MISSING',
        message: 'CSRF token (SNlM0e) not available on page.',
        retryable: true,
      },
    };
  }

  const body = new URLSearchParams();
  body.set('f.req', JSON.stringify([null, paramsJson]));
  body.set('at', auth.snlm0e);

  const urlParams = new URLSearchParams();
  if (auth.authuser > 0) {
    urlParams.set('authuser', String(auth.authuser));
  }
  const wiz = window.WIZ_global_data ?? {};
  if (wiz.cfb2h) {
    urlParams.set('bl', String(wiz.cfb2h));
  }
  if (wiz.FdrFJe) {
    urlParams.set('f.sid', String(wiz.FdrFJe));
  }
  urlParams.set('hl', 'en-CA');
  urlParams.set('rt', 'c');
  urlParams.set('_reqid', String(Math.floor(Math.random() * 900000) + 100000));
  const qs = urlParams.toString();
  const url = qs ? QUERY_URL + '?' + qs : QUERY_URL;

  try {
    const headers = {
      'Content-Type': 'application/x-www-form-urlencoded;charset=UTF-8',
      'X-Same-Domain': '1',
    };
    if (traceparent) {
      headers['traceparent'] = traceparent;
    }
    const response = await fetch(url, {
      method: 'POST',
      credentials: 'include',
      headers,
      body: body.toString(),
    });

    if (response.status === 400) {
      return {
        ok: false,
        error: {
          code: 'UPSTREAM_SCHEMA_DRIFT',
          message: 'Upstream returned HTTP 400 Bad Request (schema drift detected).',
          retryable: false,
        },
      };
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let fullText = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) {
        break;
      }
      fullText += decoder.decode(value, { stream: true });
    }
    // Flush the decoder.
    fullText += decoder.decode();

    // Strip anti-XSSI prefix.
    const stripped = fullText.startsWith(')]}\'\\n')
      ? fullText.slice(5)
      : fullText.startsWith(')]}\'')
      ? fullText.slice(4)
      : fullText;

    return { ok: true, body: stripped };
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'STREAM_ERROR',
        message: err instanceof Error ? err.message : 'Unknown stream error',
        retryable: true,
      },
    };
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

async function getCachedSessionUrl(key) {
  if (typeof chrome !== 'undefined' && chrome.storage?.session) {
    try {
      const res = await chrome.storage.session.get(key);
      return res ? res[key] : null;
    } catch (_) {
      return null;
    }
  }
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      return window.sessionStorage.getItem(key);
    } catch (_) {
      return null;
    }
  }
  return null;
}

async function setCachedSessionUrl(key, url) {
  if (typeof chrome !== 'undefined' && chrome.storage?.session) {
    try {
      await chrome.storage.session.set({ [key]: url });
      return;
    } catch (_) {}
  }
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      window.sessionStorage.setItem(key, url);
    } catch (_) {}
  }
}

async function removeCachedSessionUrl(key) {
  if (typeof chrome !== 'undefined' && chrome.storage?.session) {
    try {
      await chrome.storage.session.remove(key);
      return;
    } catch (_) {}
  }
  if (typeof window !== 'undefined' && window.sessionStorage) {
    try {
      window.sessionStorage.removeItem(key);
    } catch (_) {}
  }
}

/**
 * Hardened Scotty Upload Handler with Session URL Caching & Resumability (P-02).
 *
 * @param {string} sourceId
 * @param {string} filename
 * @param {string} notebookId
 * @param {Uint8Array} fileBytes
 * @param {number} [authuserOverride]
 * @returns {Promise<{ok: true, sourceId: string} | {ok: false, error: {code: string, message: string, retryable: boolean}}>}
 */
async function executeResumableScottyUpload(sourceId, filename, notebookId, fileBytes, authuserOverride) {
  const auth = typeof getAuthContext === 'function' ? getAuthContext() : { authuser: 0 };
  const authuser = typeof authuserOverride === 'number' ? authuserOverride : auth.authuser;
  const sessionKey = getSessionStorageKey(notebookId, sourceId);
  let sessionUrl = null;
  let startOffset = 0;

  // 1. Check for cached session URL in storage
  try {
    const cached = await getCachedSessionUrl(sessionKey);
    if (cached) {
      sessionUrl = cached;
      try {
        const queryRes = await queryScottySessionOffset(sessionUrl);
        if (queryRes.status === 'final') {
          await removeCachedSessionUrl(sessionKey);
          return { ok: true, sourceId };
        }
        startOffset = queryRes.offset;
        console.log(`[scotty] Resuming upload for ${sourceId} from server offset: ${startOffset}`);
      } catch (err) {
        console.warn('[scotty] Cached session query failed, creating fresh session.', err);
        sessionUrl = null;
        startOffset = 0;
        await removeCachedSessionUrl(sessionKey);
      }
    }
  } catch (err) {
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

      await setCachedSessionUrl(sessionKey, sessionUrl);
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

    try {
      await removeCachedSessionUrl(sessionKey);
    } catch (_) {}

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

/**
 * Scotty upload dispatcher converting base64 payload to bytes.
 */
async function executeScottyUpload(sourceId, filename, notebookId, fileBase64, authuserOverride) {
  let fileBytes;
  try {
    const binary = atob(fileBase64);
    fileBytes = new Uint8Array(binary.length);
    for (let i = 0; i < binary.length; i++) {
      fileBytes[i] = binary.charCodeAt(i);
    }
  } catch (err) {
    return {
      ok: false,
      error: {
        code: 'DECODE_ERROR',
        message: 'Failed to decode file bytes.',
        retryable: false,
      },
    };
  }

  return await executeResumableScottyUpload(sourceId, filename, notebookId, fileBytes, authuserOverride);
}

// In-page chunk collector
const chunkCollectors = new Map();

async function handleScottyChunk(payload) {
  const { sourceId, filename, notebookId, chunkIndex, totalChunks, isLastChunk, chunkData } = payload;
  if (!chunkCollectors.has(sourceId)) {
    chunkCollectors.set(sourceId, {
      chunks: new Array(totalChunks),
      received: 0,
      totalChunks,
      filename,
      notebookId,
    });
  }

  const collector = chunkCollectors.get(sourceId);
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
    chunkCollectors.delete(sourceId);
    return await executeResumableScottyUpload(
      sourceId,
      collector.filename,
      collector.notebookId,
      fullBytes,
      payload.authuser
    );
  }

  return { ok: true, chunkIndex, sourceId };
}

// ---------------------------------------------------------------------------
// Command dispatcher — window.addEventListener('message')
// ---------------------------------------------------------------------------

window.addEventListener('message', async (event) => {
  // Accept only messages from our own page (content_script relay).
  if (event.source !== window) {
    return;
  }

  const msg = event.data;
  if (!msg || msg.source !== 'mcp_bridge_cmd') {
    return;
  }

  const { command, requestId, payload } = msg;

  if (!command || !requestId) {
    return;
  }

  // Pre-flight Account Identity Guard on Mutations (P-03 / v4.2 Polish)
  const preflight = verifyAccountIdentityPreflight(command, payload);
  if (!preflight.ok) {
    const targetOrigin = window.location.origin || 'https://notebook.google.com';
    window.postMessage(
      {
        source: 'page_main_result',
        requestId,
        result: preflight,
      },
      targetOrigin
    );
    return;
  }

  let result;
  try {
    switch (command) {
      case 'batchexecute':
        result = await executeBatchexecute(
          payload.rpcId,
          payload.paramsJson,
          payload.notebookId ?? null,
          payload.traceparent ?? null
        );
        break;

      case 'query_stream':
        result = await executeQueryStream(
          payload.paramsJson,
          payload.traceparent ?? null
        );
        break;

      case 'scotty_upload':
        result = await executeScottyUpload(
          payload.sourceId,
          payload.filename,
          payload.notebookId,
          payload.fileBase64,
          payload.authuser
        );
        break;

      case 'scotty_chunk':
        result = await handleScottyChunk(payload);
        break;

      case 'HEARTBEAT_PING':
      case 'ping':
        result = {
          ok: true,
          command: 'HEARTBEAT_PONG',
          type: 'pong',
          status: 'pong',
          timestamp: Date.now(),
        };
        break;

      default:
        result = {
          ok: false,
          error: { code: 'UNKNOWN_COMMAND', message: 'Unrecognised command.', retryable: false },
        };
    }
  } catch (err) {
    result = {
      ok: false,
      error: {
        code: 'DISPATCH_ERROR',
        message: err instanceof Error ? err.message : 'Dispatch error.',
        retryable: false,
      },
    };
  }

  // Echo traceparent in result if provided
  if (payload?.traceparent && result && typeof result === 'object') {
    result.traceparent = payload.traceparent;
  }

  // Post result back. CRITICAL: result must never contain SNlM0e, cookie values,
  // ya29 tokens, or raw HTTP response headers.
  const targetOrigin = window.location.origin || 'https://notebook.google.com';
  window.postMessage(
    {
      source: 'page_main_result',
      requestId,
      result,
    },
    targetOrigin
  );
});

// ---------------------------------------------------------------------------
// Initial ready signal — notify content_script that page-main is live
// ---------------------------------------------------------------------------

(function sendReadySignal() {
  const auth = getAuthContext();
  const targetOrigin = window.location.origin || 'https://notebook.google.com';
  // Only the authuser index (a number) is included — no tokens.
  window.postMessage(
    {
      source: 'page_main_result',
      type: 'ready',
      authuser: auth.authuser,
    },
    targetOrigin
  );

  // Expose helpers for testing and service worker interoperability
  globalThis.getSessionStorageKey = getSessionStorageKey;
  globalThis.queryScottySessionOffset = queryScottySessionOffset;
  globalThis.executeResumableScottyUpload = executeResumableScottyUpload;
  globalThis.inspectRequestBodySafely = inspectRequestBodySafely;
  globalThis.executeBatchexecute = executeBatchexecute;
  globalThis.executeQueryStream = executeQueryStream;
})();
}
